import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["RELATIONBOARD_DB"] = _tmp.name

import app as app_module  # noqa: E402


class RelationBoardTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM relations")
            conn.execute("DELETE FROM characters")
            conn.commit()

    # ---- helpers ----
    def add_char(self, name, memo=""):
        return self.client.post("/characters", data={"name": name, "memo": memo})

    def char_ids(self):
        with app_module.app.app_context():
            rows = app_module.get_db().execute("SELECT id FROM characters ORDER BY id").fetchall()
            return [r["id"] for r in rows]

    def counts(self):
        with app_module.app.app_context():
            db = app_module.get_db()
            c = db.execute("SELECT COUNT(*) AS n FROM characters").fetchone()["n"]
            r = db.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"]
            return c, r

    def add_pair_with_relation(self, label="友人"):
        self.add_char("ココア", "主人公")
        self.add_char("モカ", "理知的")
        a, b = self.char_ids()
        res = self.client.post("/relations", data={"char_a": a, "char_b": b, "label": label})
        return res, a, b

    # ---- tests ----
    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_empty(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("キャラ相関図ボード", body)
        self.assertIn("まだキャラクターが登録されていません", body)

    def test_add_character(self):
        res = self.add_char("ココア", "紅茶好き")
        self.assertEqual(res.status_code, 302)
        chars, rels = self.counts()
        self.assertEqual(chars, 1)
        self.assertEqual(rels, 0)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("ココア", body)
        self.assertIn("紅茶好き", body)

    def test_add_character_empty_name_rejected(self):
        self.add_char("   ")
        self.add_char("")
        chars, _ = self.counts()
        self.assertEqual(chars, 0)

    def test_add_relation_and_svg_on_page(self):
        res, a, b = self.add_pair_with_relation("ライバル")
        self.assertEqual(res.status_code, 302)
        chars, rels = self.counts()
        self.assertEqual((chars, rels), (2, 1))
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("<svg", body)
        self.assertIn("ココア", body)
        self.assertIn("モカ", body)
        self.assertIn("ライバル", body)
        self.assertIn("<line", body)

    def test_build_svg_contains_names_and_label(self):
        chars = [
            {"id": 1, "name": "チャイ", "memo": ""},
            {"id": 2, "name": "モカ", "memo": ""},
            {"id": 3, "name": "ココア", "memo": ""},
        ]
        rels = [{"id": 1, "char_a_id": 1, "char_b_id": 3, "label": "家族"}]
        svg = app_module.build_svg(chars, rels)
        self.assertTrue(svg.startswith("<svg"))
        for name in ("チャイ", "モカ", "ココア"):
            self.assertIn(name, svg)
        self.assertIn("家族", svg)
        self.assertEqual(svg.count("<circle"), 3)
        self.assertEqual(svg.count("<line"), 1)

    def test_build_svg_single_character_centered(self):
        svg = app_module.build_svg([{"id": 1, "name": "ソロ", "memo": ""}], [])
        self.assertIn("ソロ", svg)
        self.assertNotIn("<line", svg)

    def test_delete_character_removes_relations(self):
        # フォームのプレースホルダ文言と重ならない名前を使う
        self.add_char("タロウ")
        self.add_char("ハナコ")
        a, b = self.char_ids()
        self.client.post("/relations", data={"char_a": a, "char_b": b, "label": "家族"})
        res = self.client.post(f"/characters/{a}/delete")
        self.assertEqual(res.status_code, 302)
        chars, rels = self.counts()
        self.assertEqual(chars, 1)
        self.assertEqual(rels, 0)
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("タロウ", body)
        self.assertIn("ハナコ", body)

    def test_delete_relation(self):
        self.add_pair_with_relation()
        with app_module.app.app_context():
            rid = app_module.get_db().execute("SELECT id FROM relations").fetchone()["id"]
        res = self.client.post(f"/relations/{rid}/delete")
        self.assertEqual(res.status_code, 302)
        chars, rels = self.counts()
        self.assertEqual((chars, rels), (2, 0))

    def test_relation_same_character_rejected(self):
        self.add_char("ココア")
        (only,) = self.char_ids()
        self.client.post("/relations", data={"char_a": only, "char_b": only, "label": "友人"})
        _, rels = self.counts()
        self.assertEqual(rels, 0)

    def test_relation_unknown_character_rejected(self):
        self.add_char("ココア")
        (only,) = self.char_ids()
        res = self.client.post("/relations", data={"char_a": only, "char_b": 9999, "label": "友人"})
        self.assertEqual(res.status_code, 400)
        _, rels = self.counts()
        self.assertEqual(rels, 0)

    def test_svg_escapes_user_input(self):
        evil = '<script>alert("x")</script>'
        chars = [
            {"id": 1, "name": evil, "memo": ""},
            {"id": 2, "name": "相手", "memo": ""},
        ]
        rels = [{"id": 1, "char_a_id": 1, "char_b_id": 2, "label": "<b>友人</b>"}]
        svg = app_module.build_svg(chars, rels)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        self.assertNotIn("<b>友人</b>", svg)
        self.assertIn("&lt;b&gt;友人&lt;/b&gt;", svg)

    def test_page_escapes_user_input(self):
        self.add_char("<img src=x onerror=alert(1)>", "<b>太字</b>")
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<img src=x onerror=alert(1)>", body)
        self.assertIn("&lt;img", body)
        self.assertNotIn("<b>太字</b>", body)
        self.assertIn("&lt;b&gt;", body)


if __name__ == "__main__":
    unittest.main()
