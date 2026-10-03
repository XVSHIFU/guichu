"""User-authored assistant preferences; never an authorization source."""
import json


def initialize(connection):
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS agent_preferences (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')


def read(connection):
    with connection() as db:
        row = db.execute('SELECT payload FROM agent_preferences WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'instructions': ''}


def dispatch(connection, body):
    if not isinstance(body, dict) or set(body) - {'instructions'}:
        return {'error': '偏好参数无效'}, 400
    if 'instructions' in body:
        value = body['instructions']
        if not isinstance(value, str) or len(value) > 2000:
            return {'error': '使用偏好最多 2000 字'}, 400
        with connection() as db:
            db.execute('INSERT INTO agent_preferences VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (json.dumps({'instructions': value.strip()}, ensure_ascii=False),))
    return {'preferences': read(connection)}, 200
