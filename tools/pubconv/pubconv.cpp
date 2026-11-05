// pubconv: PubDesign's bundled Microsoft Publisher reader.
//
//   pubconv in.pub out.fodg        Publisher file -> flat ODF drawing (read by pub_import.FodgReader)
//   pubconv --meta in out.png W H  WMF/EMF picture -> transparent PNG (Windows only, GDI+)
//
// Built from libmspub + librevenge + libodfgen (MPL 2.0), the same Publisher reader LibreOffice uses.
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <librevenge/librevenge.h>
#include <librevenge-stream/librevenge-stream.h>
#include <libmspub/libmspub.h>
#include <libodfgen/libodfgen.hxx>

#ifdef _WIN32
#include <windows.h>
#include <gdiplus.h>
#endif

namespace {

class XmlWriter : public OdfDocumentHandler
{
public:
    explicit XmlWriter(std::string &out) : m_out(out), m_open(false) {}
    void startDocument() override
    {
        m_out += "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    }
    void endDocument() override { closeStart(); }
    void startElement(const char *name, const librevenge::RVNGPropertyList &props) override
    {
        closeStart();
        m_out += "<";
        m_out += name;
        librevenge::RVNGPropertyList::Iter i(props);
        for (i.rewind(); i.next();)
        {
            // child property lists are not attributes
            if (i.child())
                continue;
            librevenge::RVNGString v;
            v.appendEscapedXML(i()->getStr());
            m_out += " ";
            m_out += i.key();
            m_out += "=\"";
            m_out += v.cstr();
            m_out += "\"";
        }
        m_open = true;
    }
    void endElement(const char *name) override
    {
        if (m_open)
        {
            m_out += "/>";
            m_open = false;
        }
        else
        {
            m_out += "</";
            m_out += name;
            m_out += ">";
        }
    }
    void characters(const librevenge::RVNGString &s) override
    {
        closeStart();
        librevenge::RVNGString v;
        v.appendEscapedXML(s);
        m_out += v.cstr();
    }

private:
    void closeStart()
    {
        if (m_open)
        {
            m_out += ">";
            m_open = false;
        }
    }
    std::string &m_out;
    bool m_open;
};

// Passes everything through but can hide the document-properties streams. Some Publisher
// files have property streams libmspub can't read, and it then gives up on the whole file.
class FilteredStream : public librevenge::RVNGInputStream
{
public:
    FilteredStream(librevenge::RVNGInputStream *in, bool hideMeta) : m_in(in), m_hide(hideMeta) {}
    bool isStructured() override { return m_in->isStructured(); }
    unsigned subStreamCount() override { return m_in->subStreamCount(); }
    const char *subStreamName(unsigned id) override { return m_in->subStreamName(id); }
    bool existsSubStream(const char *name) override { return !hidden(name) && m_in->existsSubStream(name); }
    librevenge::RVNGInputStream *getSubStreamByName(const char *name) override
    {
        return hidden(name) ? nullptr : m_in->getSubStreamByName(name);
    }
    librevenge::RVNGInputStream *getSubStreamById(unsigned id) override
    {
        const char *name = m_in->subStreamName(id);
        return (name && hidden(name)) ? nullptr : m_in->getSubStreamById(id);
    }
    const unsigned char *read(unsigned long n, unsigned long &got) override { return m_in->read(n, got); }
    int seek(long off, librevenge::RVNG_SEEK_TYPE t) override { return m_in->seek(off, t); }
    long tell() override { return m_in->tell(); }
    bool isEnd() override { return m_in->isEnd(); }

private:
    bool hidden(const char *name) const
    {
        return m_hide && name && strstr(name, "SummaryInformation") != nullptr;
    }
    librevenge::RVNGInputStream *m_in;
    bool m_hide;
};

bool parseInto(const char *in, bool hideMeta, std::string &xml)
{
    librevenge::RVNGFileStream file(in);
    FilteredStream input(&file, hideMeta);
    if (!libmspub::MSPUBDocument::isSupported(&input))
        return false;
    xml.clear();
    XmlWriter writer(xml);
    OdgGenerator gen;
    gen.addDocumentHandler(&writer, ODF_FLAT_XML);
    input.seek(0, librevenge::RVNG_SEEK_SET);
    return libmspub::MSPUBDocument::parse(&input, &gen);
}

int convertPub(const char *in, const char *out)
{
    {
        librevenge::RVNGFileStream probe(in);
        if (!libmspub::MSPUBDocument::isSupported(&probe))
        {
            fprintf(stderr, "not a supported Publisher file\n");
            return 2;
        }
    }
    std::string xml;
    if (!parseInto(in, false, xml) && !parseInto(in, true, xml))
    {
        fprintf(stderr, "could not read the Publisher file\n");
        return 4;
    }
    FILE *f = fopen(out, "wb");
    if (!f)
    {
        fprintf(stderr, "cannot write %s\n", out);
        return 3;
    }
    fwrite(xml.data(), 1, xml.size(), f);
    fclose(f);
    return 0;
}

#ifdef _WIN32
int CLSIDPng(CLSID *clsid)
{
    UINT num = 0, size = 0;
    Gdiplus::GetImageEncodersSize(&num, &size);
    if (!size)
        return -1;
    std::vector<char> buf(size);
    Gdiplus::ImageCodecInfo *info = reinterpret_cast<Gdiplus::ImageCodecInfo *>(buf.data());
    Gdiplus::GetImageEncoders(num, size, info);
    for (UINT i = 0; i < num; ++i)
        if (wcscmp(info[i].MimeType, L"image/png") == 0)
        {
            *clsid = info[i].Clsid;
            return 0;
        }
    return -1;
}

std::wstring widen(const char *s)
{
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0);
    std::wstring w(n ? n - 1 : 0, L'\0');
    if (n > 1)
        MultiByteToWideChar(CP_UTF8, 0, s, -1, &w[0], n);
    return w;
}

int convertMeta(const char *in, const char *out, int w, int h)
{
    Gdiplus::GdiplusStartupInput si;
    ULONG_PTR token;
    if (Gdiplus::GdiplusStartup(&token, &si, nullptr) != Gdiplus::Ok)
        return 5;
    int rc = 6;
    {
        Gdiplus::Metafile meta(widen(in).c_str());
        if (meta.GetLastStatus() == Gdiplus::Ok)
        {
            Gdiplus::Bitmap bmp(w, h, PixelFormat32bppARGB);
            {
                Gdiplus::Graphics g(&bmp);
                g.Clear(Gdiplus::Color(0, 0, 0, 0));
                g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
                g.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAliasGridFit);
                g.SetInterpolationMode(Gdiplus::InterpolationModeHighQualityBicubic);
                g.DrawImage(&meta, 0, 0, w, h);
            }
            CLSID png;
            if (CLSIDPng(&png) == 0 && bmp.Save(widen(out).c_str(), &png, nullptr) == Gdiplus::Ok)
                rc = 0;
        }
    }
    Gdiplus::GdiplusShutdown(token);
    return rc;
}
#endif

} // namespace

int main(int argc, char **argv)
{
    if (argc == 6 && strcmp(argv[1], "--meta") == 0)
    {
#ifdef _WIN32
        return convertMeta(argv[2], argv[3], atoi(argv[4]), atoi(argv[5]));
#else
        fprintf(stderr, "--meta needs Windows\n");
        return 7;
#endif
    }
    if (argc == 2 && strcmp(argv[1], "--version") == 0)
    {
        puts("pubconv 1");
        return 0;
    }
    if (argc != 3)
    {
        fprintf(stderr, "usage: pubconv in.pub out.fodg | pubconv --meta in.emf out.png width height\n");
        return 1;
    }
    return convertPub(argv[1], argv[2]);
}
