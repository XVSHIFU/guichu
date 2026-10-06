import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agent_preferences
from agent.context import build

class InstructionsTests(unittest.TestCase):
    def test_long_user_instructions_saved_and_used_without_truncation(self):
        db=sqlite3.connect(':memory:')
        @contextlib.contextmanager
        def connection():
            yield db
            db.commit()
        agent_preferences.initialize(connection)
        text='指令'*3999+'结尾'
        result,status=agent_preferences.dispatch(connection,{'instructions':text})
        self.assertEqual(status,200)
        self.assertEqual(agent_preferences.read(connection)['instructions'],text)
        messages=build({'input':'解释软件用途'},[],[],preferences={'instructions':text})
        self.assertTrue(any(text in m.get('content','') for m in messages))
        self.assertEqual(agent_preferences.dispatch(connection,{'instructions':text+'超限'})[1],400)
        db.close()
