import copy
import json
import unittest
from pathlib import Path
from model import Document, TextComment, DesignError


class CommentTests(unittest.TestCase):
    def test_roundtrip_and_hdl_unchanged(self):
        path = Path(__file__).resolve().parent.parent / 'examples/demo.vsch'
        doc = Document.deserialize(json.loads(path.read_text(encoding='utf-8')))
        before = [doc.verilog(lang) for lang in ('verilog', 'systemverilog')]
        doc.comments.append(TextComment(text='Описание узла\nendmodule; /* тест */', x=-200, y=-100))
        restored = Document.deserialize(doc.serialize())
        self.assertEqual(restored.serialize(), doc.serialize())
        self.assertEqual([restored.verilog(lang) for lang in ('verilog', 'systemverilog')], before)
        restored.comments[0].text = 'Новое описание'
        self.assertEqual(restored.verilog(), before[0])

    def test_old_documents(self):
        for version in range(1, 5):
            data = Document().serialize()
            data['version'] = version
            del data['comments']
            self.assertEqual(Document.deserialize(data).comments, [])

    def test_invalid_comments(self):
        for field, value in [('text', ''), ('text', '\0'), ('x', 3), ('y', 100000020),
                             ('w', 80), ('font_size', 33), ('id', '')]:
            with self.subTest(field=field):
                comment = TextComment()
                setattr(comment, field, value)
                with self.assertRaises(DesignError):
                    Document(comments=[comment]).validate()

    def test_duplicate_ids(self):
        comment = TextComment()
        with self.assertRaises(DesignError):
            Document(comments=[comment, copy.deepcopy(comment)]).validate()
