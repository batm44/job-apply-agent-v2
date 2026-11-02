"""Generate simple, text-based DOCX documents without a third-party dependency."""
import re
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def to_docx(text, target):
    paragraphs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        heading = line.startswith('#')
        line = re.sub(r'^#+\s*', '', line).replace('**', '')
        props = '<w:b/><w:sz w:val="25"/>' if heading else '<w:sz w:val="21"/>'
        paragraphs.append('<w:p><w:pPr><w:spacing w:after="100"/></w:pPr><w:r><w:rPr>' + props + '</w:rPr><w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>')
    content = '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ''.join(paragraphs) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850"/></w:sectPr></w:body></w:document>'
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', content)


def export_folder(folder):
    folder = Path(folder)
    resume = folder / 'resume.md'
    if not resume.is_file():
        raise ValueError('Prepare a truthful tailored resume.md before exporting')
    output = folder / 'resume.docx'
    to_docx(resume.read_text(encoding='utf-8'), output)
    results = {'resume': str(output)}
    letter = folder / 'cover_letter.md'
    if letter.is_file():
        target = folder / 'cover_letter.docx'
        to_docx(letter.read_text(encoding='utf-8'), target)
        results['cover_letter'] = str(target)
    return results
