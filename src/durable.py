"""T2 Durable 会话持久化与崩溃恢复。

思想来源：图05 Pi Durable——单文件 SQLite + 原子提交序列 + 不可变事件记录，
"日志即状态"：不存当前快照，只存"发生过什么"，恢复=重放事件。

在脓毒症场景的用途（长程病程跟踪是小时级长任务）：
- 每个时间窗评估完即写入事件（原子提交），进程被 kill 不丢已完成的病程。
- 重启后打开同一 session 文件即可从断点续跑（safe 事件重放、unsafe 标记中断）。
- 支持按患者回放整个决策链；支持 Fork 出"如果换方案会怎样"的对照分支。
"""
import os
import json
import sqlite3
import time
import config


class DurableSession:
    """一个患者病程评估会话 = 一个 SQLite 事件日志文件。"""

    def __init__(self, session_id, session_dir=None):
        self.session_dir = session_dir or config.SESSION_DIR
        os.makedirs(self.session_dir, exist_ok=True)
        self.session_id = session_id
        self.path = os.path.join(self.session_dir, f"{session_id}.sqlite3")
        self.db = sqlite3.connect(self.path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            type TEXT,          -- timeline_eval / agent_msg / skill_activate / verdict / fork
            safe INTEGER,       -- 1=可安全重放 0=不可重放(中断)
            payload TEXT        -- JSON
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS meta(
            k TEXT PRIMARY KEY, v TEXT)""")
        self.db.commit()

    # ---------- 写入（原子提交）----------
    def append(self, type_, payload, safe=True):
        self.db.execute(
            "INSERT INTO events(ts,type,safe,payload) VALUES(?,?,?,?)",
            (time.time(), type_, 1 if safe else 0, json.dumps(payload, ensure_ascii=False)))
        self.db.commit()   # 每次写入即提交 = 原子提交，崩溃不丢
        return self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))
        self.db.commit()

    # ---------- 恢复（重放）----------
    def recover(self):
        """重放所有 safe 事件，重建状态；unsafe 事件标记为中断待处理。"""
        rows = self.db.execute(
            "SELECT seq,type,safe,payload FROM events ORDER BY seq").fetchall()
        state = {"events": [], "completed_steps": [], "interrupted": []}
        for seq, type_, safe, payload in rows:
            item = {"seq": seq, "type": type_, "payload": json.loads(payload)}
            if safe:
                state["events"].append(item)
                state["completed_steps"].append((type_, item["payload"]))
            else:
                state["interrupted"].append(item)
        return state

    def done_steps(self, type_):
        """已完成的某类步骤的标识集合（用于断点续跑去重）。"""
        rows = self.db.execute(
            "SELECT payload FROM events WHERE type=? AND safe=1", (type_,)).fetchall()
        return {json.loads(r[0]).get("step_id") for r in rows}

    # ---------- Fork 分支 ----------
    def fork(self, new_session_id):
        """复制当前事件日志到新会话（用于"如果换方案"对照分支）。"""
        forked = DurableSession(new_session_id, self.session_dir)
        rows = self.db.execute(
            "SELECT ts,type,safe,payload FROM events ORDER BY seq").fetchall()
        for ts, type_, safe, payload in rows:
            forked.db.execute(
                "INSERT INTO events(ts,type,safe,payload) VALUES(?,?,?,?)",
                (ts, type_, safe, payload))
        forked.db.commit()
        forked.append("fork", {"from": self.session_id, "to": new_session_id})
        return forked

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self):
        self.db.close()
