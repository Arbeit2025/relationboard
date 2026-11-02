"""キャラ相関図ボード relationboard

自作キャラクター同士の関係を登録し、円周上にキャラを配置した相関図
（SVG）をサーバー側で生成して表示する小さなボード。
キャラクター（名前・任意メモ）と関係（キャラA・キャラB・関係ラベル）を
SQLite に保存する。外部 JS ライブラリは使わない。
単一ファイル Flask + SQLite。
"""
import html
import math
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("RELATIONBOARD_DB", os.path.join(os.path.dirname(__file__), "relationboard.db"))

LABEL_PRESETS = ["友人", "ライバル", "家族", "師弟", "恋人", "同僚", "敵対"]

# SVG の描画パラメータ
SVG_SIZE = 640
SVG_CENTER = SVG_SIZE // 2
SVG_RADIUS = 225
NODE_RADIUS = 38


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            memo TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            char_a_id INTEGER NOT NULL,
            char_b_id INTEGER NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def character_positions(characters):
    """キャラ id -> (x, y)。円周上に均等配置（1人だけなら中心）。"""
    n = len(characters)
    positions = {}
    if n == 1:
        positions[characters[0]["id"]] = (float(SVG_CENTER), float(SVG_CENTER))
        return positions
    for i, c in enumerate(characters):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        x = SVG_CENTER + SVG_RADIUS * math.cos(angle)
        y = SVG_CENTER + SVG_RADIUS * math.sin(angle)
        positions[c["id"]] = (x, y)
    return positions


def build_svg(characters, relations):
    """相関図の SVG 文字列を生成する。名前・ラベルは HTML エスケープする。"""
    positions = character_positions(characters)
    parts = [
        f'<svg viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" width="100%" '
        f'style="max-width:{SVG_SIZE}px;background:#fdfdf8;border:1px solid #ccc;border-radius:8px" '
        f'role="img" aria-label="キャラクター相関図">'
    ]
    # 関係の線とラベル
    for r in relations:
        a = positions.get(r["char_a_id"])
        b = positions.get(r["char_b_id"])
        if a is None or b is None:
            continue
        parts.append(
            f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
            f'stroke="#999" stroke-width="2"/>'
        )
        if r["label"]:
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            parts.append(
                f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" font-size="13" '
                f'fill="#555" style="paint-order:stroke" stroke="#fdfdf8" stroke-width="4">'
                f'{html.escape(r["label"])}</text>'
            )
    # キャラのノード
    for c in characters:
        x, y = positions[c["id"]]
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{NODE_RADIUS}" fill="#eaf2ff" '
            f'stroke="#5b7fb4" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dominant-baseline="central" '
            f'font-size="14" fill="#222">{html.escape(c["name"])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>キャラ相関図ボード</title>
<style>body{font-family:sans-serif;max-width:760px;margin:2em auto;padding:0 1em}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3em .5em}
.note{background:#f4f4f4;border:1px solid #ccc;padding:.8em;border-radius:6px}</style>
</head><body>
<h1>キャラ相関図ボード</h1>
<p>自作キャラクター同士の関係を登録して、相関図で眺めるためのボードです。キャラを登録し、関係（友人／ライバル／家族など）を結ぶと、下の図に線とラベルが表示されます。</p>
<p class="note">データはこのアプリの SQLite に保存されます。Render 無料プランでは再デプロイ等でデータが消える場合があります。</p>

<h2>相関図</h2>
{% if characters %}
{{ svg|safe }}
{% else %}
<p>まだキャラクターが登録されていません。下のフォームから追加してください。</p>
{% endif %}

<h2>キャラクターを追加</h2>
<form method="post" action="{{ url_for('add_character') }}">
  <label>名前 <input type="text" name="name" required placeholder="例：ココア"></label><br>
  <label>メモ <input type="text" name="memo" size="50" placeholder="任意（例：主人公、紅茶好き）"></label><br>
  <button type="submit">追加する</button>
</form>

<h2>キャラクター一覧（{{ characters|length }}人）</h2>
<table>
<tr><th>名前</th><th>メモ</th><th>操作</th></tr>
{% for c in characters %}
<tr>
  <td>{{ c.name }}</td>
  <td>{{ c.memo }}</td>
  <td><form method="post" action="{{ url_for('delete_character', cid=c.id) }}" style="display:inline" onsubmit="return confirm('このキャラクターを削除しますか？（関係も一緒に消えます）')"><button>削除</button></form></td>
</tr>
{% else %}
<tr><td colspan="3">登録されたキャラクターはまだありません</td></tr>
{% endfor %}
</table>

<h2>関係を追加</h2>
{% if characters|length >= 2 %}
<form method="post" action="{{ url_for('add_relation') }}">
  <label>キャラA
    <select name="char_a">{% for c in characters %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></label>
  <label>キャラB
    <select name="char_b">{% for c in characters %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></label><br>
  <label>関係ラベル <input type="text" name="label" list="label-presets" placeholder="例：友人"></label>
  <datalist id="label-presets">{% for l in label_presets %}<option value="{{ l }}">{% endfor %}</datalist>
  <button type="submit">関係を追加する</button>
</form>
{% else %}
<p>関係を追加するにはキャラクターが2人以上必要です。</p>
{% endif %}

<h2>関係一覧（{{ relations_view|length }}件）</h2>
<table>
<tr><th>キャラA</th><th>関係</th><th>キャラB</th><th>操作</th></tr>
{% for r in relations_view %}
<tr>
  <td>{{ r.a_name }}</td>
  <td>{{ r.label }}</td>
  <td>{{ r.b_name }}</td>
  <td><form method="post" action="{{ url_for('delete_relation', rid=r.id) }}" style="display:inline" onsubmit="return confirm('この関係を削除しますか？')"><button>削除</button></form></td>
</tr>
{% else %}
<tr><td colspan="4">登録された関係はまだありません</td></tr>
{% endfor %}
</table>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    characters = db.execute("SELECT * FROM characters ORDER BY id").fetchall()
    relations = db.execute("SELECT * FROM relations ORDER BY id").fetchall()
    names = {c["id"]: c["name"] for c in characters}
    relations_view = [
        {
            "id": r["id"],
            "label": r["label"],
            "a_name": names.get(r["char_a_id"], "（不明）"),
            "b_name": names.get(r["char_b_id"], "（不明）"),
        }
        for r in relations
    ]
    return render_template_string(
        INDEX,
        characters=characters,
        relations_view=relations_view,
        svg=build_svg(characters, relations),
        label_presets=LABEL_PRESETS,
    )


@app.route("/characters", methods=["POST"])
def add_character():
    name = (request.form.get("name") or "").strip()
    if name:
        db = get_db()
        db.execute(
            "INSERT INTO characters(name, memo, created_at) VALUES(?, ?, ?)",
            (name, (request.form.get("memo") or "").strip(), now_str()),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/characters/<int:cid>/delete", methods=["POST"])
def delete_character(cid):
    db = get_db()
    db.execute("DELETE FROM relations WHERE char_a_id = ? OR char_b_id = ?", (cid, cid))
    db.execute("DELETE FROM characters WHERE id = ?", (cid,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/relations", methods=["POST"])
def add_relation():
    try:
        a_id = int(request.form.get("char_a") or "")
        b_id = int(request.form.get("char_b") or "")
    except ValueError:
        return redirect(url_for("index"))
    if a_id == b_id:
        return redirect(url_for("index"))
    db = get_db()
    ids = {r["id"] for r in db.execute("SELECT id FROM characters").fetchall()}
    if a_id not in ids or b_id not in ids:
        abort(400)
    label = (request.form.get("label") or "").strip() or "関係"
    db.execute(
        "INSERT INTO relations(char_a_id, char_b_id, label, created_at) VALUES(?, ?, ?, ?)",
        (a_id, b_id, label, now_str()),
    )
    db.commit()
    return redirect(url_for("index"))


@app.route("/relations/<int:rid>/delete", methods=["POST"])
def delete_relation(rid):
    db = get_db()
    db.execute("DELETE FROM relations WHERE id = ?", (rid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
