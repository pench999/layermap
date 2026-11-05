import re
import unittest
from pathlib import Path
from urllib.parse import unquote
from fastapi.testclient import TestClient
from web_app import app,AI_DOCUMENTS
from network_model import load_model
from generate_diagram import render

class AIDocumentTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)

    def test_read_and_download_preserve_utf8_markdown_and_filenames(self):
        for identity,document in AI_DOCUMENTS.items():
            response=self.client.get('/api/ai-docs/'+identity)
            self.assertEqual(response.status_code,200)
            body=response.json()
            self.assertEqual(body['title'],document['title'])
            self.assertEqual(body['filename'],document['filename'])
            self.assertEqual(body['content'],document['file'].read_text(encoding='utf-8'))
            saved=self.client.get('/api/ai-docs/'+identity+'/download')
            self.assertEqual(saved.status_code,200)
            self.assertEqual(saved.content,document['file'].read_bytes())
            self.assertIn('text/markdown',saved.headers['content-type'])
            self.assertIn('attachment;',saved.headers['content-disposition'])
            self.assertIn(document['filename'],unquote(saved.headers['content-disposition']))
            self.assertEqual(saved.headers['x-content-type-options'],'nosniff')

    def test_unknown_ids_do_not_expose_files(self):
        for identity in ['unknown','web_app.py','network_model.py','%2Fetc%2Fpasswd']:
            self.assertEqual(self.client.get('/api/ai-docs/'+identity).status_code,404)
            self.assertEqual(self.client.get('/api/ai-docs/'+identity+'/download').status_code,404)

    def test_bundled_complete_examples_remain_valid_against_current_model(self):
        text=AI_DOCUMENTS['instructions']['file'].read_text(encoding='utf-8')
        examples=re.findall(r'~~~yaml\r?\n(.*?)~~~',text,re.S)
        self.assertEqual(len(examples),2)
        empty=load_model(examples[0]);self.assertEqual(empty['devices'],[])
        model=load_model(examples[1]);self.assertEqual(len(model['devices']),4)
        self.assertEqual(len(model['l1']['links']),4)
        self.assertIn('<svg',render(model))
        self.assertIn('l3.subnet_groups',text)
        self.assertIn('実行検証は未実施',text)
