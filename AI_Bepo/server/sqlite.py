import sqlite3
import uuid

DB_PATH="memory.db"
MAX_HISTORY=10
SESSION_ID=str(uuid.uuid4())
import threading
_db_lock = threading.Lock()

def init_db():
    conn=sqlite3.connect(DB_PATH,check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        

        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        
        "session TEXT NOT NULL, "
        

        "role TEXT NOT NULL, "
        

        "content TEXT NOT NULL, "
       

        "ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn

def save(conn,role,content):
    conn.execute(
        "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
        (SESSION_ID, role, content)
    )
    conn.commit()
    
def Load_History(conn):
    query = "SELECT role, content FROM messages WHERE session = ? ORDER BY id DESC LIMIT ?"
    rows = conn.execute(query, (SESSION_ID, MAX_HISTORY)).fetchall()
    rows.reverse()
    history=[]
    for row in rows:
        role=row[0]
        content=row[1]
        history.append({"role":role,"content":content})
    return history
def Clean(conn):
    conn.execute(
        "DELETE FROM messages WHERE session = ? AND id NOT IN "
        "(SELECT id FROM messages WHERE session = ? ORDER BY id DESC LIMIT ?)",
        (SESSION_ID, SESSION_ID, MAX_HISTORY)
    )
    conn.commit()
    