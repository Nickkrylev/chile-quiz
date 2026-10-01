"""Read question text as data; preserve source key and flag proposed corrections."""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

with zipfile.ZipFile(sys.argv[1]) as archive:
    root = ET.fromstring(archive.read('word/document.xml'))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns)]
questions = []
keys = []
in_keys = False
for line in paragraphs:
    line = line.strip()
    if not line:
        continue
    if line == 'Claves:':
        in_keys = True
        continue
    if in_keys:
        keys.append(line.translate(str.maketrans({'а':'a','с':'c'})))
        continue
    number = re.match(r'^(\d+)\.\s*(.*)', line)
    if number:
        questions.append({'id': int(number[1]), 'prompt': number[2], 'text':'', 'choices':[]})
    elif questions:
        if re.match(r'^[аa]\)', line):
            choices = re.split(r'[аaбbсcдd]\)', line)[1:]
            questions[-1]['choices'] = [x.strip() for x in choices]
        else:
            questions[-1]['text'] += ('\n' if questions[-1]['text'] else '') + line
assert len(questions) == len(keys) == 20
for q,key in zip(questions, keys):
    assert len(q['choices']) == 4, q
    q['source_correct'] = ['abcd'.index(key)]
    q['correct'] = q['source_correct'][:]
    q['suggested_correct'] = {7:[1,2],10:[3],16:[1]}.get(q['id'],q['correct'][:])
Path('data/test-uo6.json').write_text(json.dumps({'title':'Испанский язык · УО-6','source':'TEST УО-6.docx','questions':questions},ensure_ascii=False,indent=2)+'\n')
print('Imported 20 questions, 4 choices each; source keys preserved.')
