"""SQLite database manager for moderation logs and warnings."""

import aiosqlite
import json
import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path


class DatabaseManager:
    """Handles all database operations for the bot."""
    
    def __init__(self, db_path: str = "bot_data.db"):
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

        # Default timeouts: keep the bot responsive if SQLite is busy/locked.
        self._connect_timeout_s: float = 5.0
        self._busy_timeout_ms: int = 5000

    async def init_db(self) -> None:
        """
        Backward-compatible initializer used by cogs.
        Calls connect() to establish DB connection and create tables.
        """
        await self.connect()
        
    async def connect(self) -> None:
        """Establish database connection and create tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(self.db_path, timeout=self._connect_timeout_s)
        self.db.row_factory = aiosqlite.Row

        # Pragmas to reduce lock contention and avoid indefinite waits.
        try:
            await self.db.execute("PRAGMA journal_mode=WAL;")
            await self.db.execute("PRAGMA synchronous=NORMAL;")
            await self.db.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)};")
            await self.db.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            # If pragmas fail, continue with defaults.
            pass

        await self._create_tables()
        
    async def close(self) -> None:
        """Close database connection."""
        if self.db:
            await self.db.close()
            
    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        async with self.db.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    mod_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active BOOLEAN DEFAULT 1
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS mod_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    mod_id INTEGER NOT NULL,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    duration INTEGER
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS server_config (
                    guild_id INTEGER PRIMARY KEY,
                    mod_log_channel_id INTEGER,
                    allowed_admin_role_ids TEXT,
                    muted_role_id INTEGER,
                    config_data TEXT
                )
            """)
            
            await cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_warnings_guild_user 
                ON warnings(guild_id, user_id, active)
            """)
            
            await cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mod_actions_guild 
                ON mod_actions(guild_id, timestamp)
            """)
            
            await self.db.commit()
            
    # ==================== WARNINGS ====================
    
    async def add_warning(
        self, 
        guild_id: int, 
        user_id: int, 
        mod_id: int, 
        reason: str
    ) -> int:
        async with self.db.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO warnings (guild_id, user_id, mod_id, reason)
                VALUES (?, ?, ?, ?)
            """, (guild_id, user_id, mod_id, reason))
            await self.db.commit()
            return cursor.lastrowid
            
    async def get_warnings(
        self, 
        guild_id: int, 
        user_id: int, 
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        async with self.db.cursor() as cursor:
            query = """
                SELECT * FROM warnings 
                WHERE guild_id = ? AND user_id = ?
            """
            params = [guild_id, user_id]
            
            if active_only:
                query += " AND active = 1"
                
            query += " ORDER BY timestamp DESC"
            
            await cursor.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
            
    async def get_warning_count(
        self, 
        guild_id: int, 
        user_id: int, 
        active_only: bool = True
    ) -> int:
        async with self.db.cursor() as cursor:
            query = """
                SELECT COUNT(*) as count FROM warnings 
                WHERE guild_id = ? AND user_id = ?
            """
            params = [guild_id, user_id]
            
            if active_only:
                query += " AND active = 1"
                
            await cursor.execute(query, params)
            row = await cursor.fetchone()
            return row["count"] if row else 0
            
    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        async with self.db.cursor() as cursor:
            await cursor.execute("""
                UPDATE warnings SET active = 0
                WHERE guild_id = ? AND user_id = ? AND active = 1
            """, (guild_id, user_id))
            await self.db.commit()
            return cursor.rowcount
            
    # ==================== MOD ACTIONS ====================
    
    async def log_action(
        self,
        guild_id: int,
        action_type: str,
        target_id: int,
        mod_id: int,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None
    ) -> int:
        metadata_json = json.dumps(metadata) if metadata else None
        
        async with self.db.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO mod_actions 
                (guild_id, action_type, target_id, mod_id, reason, metadata, duration)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, action_type, target_id, mod_id, reason, metadata_json, duration))
            await self.db.commit()
            return cursor.lastrowid
            
    async def get_mod_actions(
        self,
        guild_id: int,
        limit: int = 50,
        action_type: Optional[str] = None,
        target_id: Optional[int] = None,
        mod_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM mod_actions WHERE guild_id = ?"
        params = [guild_id]
        
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
            
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
            
        if mod_id:
            query += " AND mod_id = ?"
            params.append(mod_id)
            
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        async with self.db.cursor() as cursor:
            await cursor.execute(query, params)
            rows = await cursor.fetchall()
            
            actions = []
            for row in rows:
                action = dict(row)
                if action["metadata"]:
                    action["metadata"] = json.loads(action["metadata"])
                actions.append(action)
                
            return actions
            
    # ==================== SERVER CONFIG ====================
    
    async def get_server_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        async with self.db.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM server_config WHERE guild_id = ?
            """, (guild_id,))
            row = await cursor.fetchone()
            
            if not row:
                return None
                
            config = dict(row)
            if config["allowed_admin_role_ids"]:
                config["allowed_admin_role_ids"] = json.loads(config["allowed_admin_role_ids"])
            if config["config_data"]:
                config["config_data"] = json.loads(config["config_data"])
                
            return config
            
    async def update_server_config(
        self,
        guild_id: int,
        mod_log_channel_id: Optional[int] = None,
        allowed_admin_role_ids: Optional[List[int]] = None,
        muted_role_id: Optional[int] = None,
        config_data: Optional[Dict[str, Any]] = None
    ) -> None:
        existing = await self.get_server_config(guild_id)
        
        if existing is None:
            admin_roles_json = json.dumps(allowed_admin_role_ids or [])
            config_json = json.dumps(config_data or {})
            
            async with self.db.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO server_config 
                    (guild_id, mod_log_channel_id, allowed_admin_role_ids, muted_role_id, config_data)
                    VALUES (?, ?, ?, ?, ?)
                """, (guild_id, mod_log_channel_id, admin_roles_json, muted_role_id, config_json))
                await self.db.commit()
        else:
            updates = []
            params = []
            
            if mod_log_channel_id is not None:
                updates.append("mod_log_channel_id = ?")
                params.append(mod_log_channel_id)
                
            if allowed_admin_role_ids is not None:
                updates.append("allowed_admin_role_ids = ?")
                params.append(json.dumps(allowed_admin_role_ids))
                
            if muted_role_id is not None:
                updates.append("muted_role_id = ?")
                params.append(muted_role_id)
                
            if config_data is not None:
                updates.append("config_data = ?")
                params.append(json.dumps(config_data))
                
            if updates:
                params.append(guild_id)
                query = f"""
                    UPDATE server_config 
                    SET {', '.join(updates)}
                    WHERE guild_id = ?
                """
                
                async with self.db.cursor() as cursor:
                    await cursor.execute(query, params)
                    await self.db.commit()
    async def update_server_setting(self, guild_id: int, key: str, value: Any) -> None:
        """Small helper to store settings in server_config.config_data"""
        existing = await self.get_server_config(guild_id)
        data = (existing.get("config_data") if existing else None) or {}
        data[key] = value
        await self.update_server_config(guild_id, config_data=data)

    async def get_server_settings(self, guild_id: int) -> Dict[str, Any]:
        """Return server settings stored in server_config.config_data"""
        existing = await self.get_server_config(guild_id)
        data = (existing.get("config_data") if existing else None) or {}
        # normalize keys used by the bot
        return {
            "log_channel": data.get("log_channel"),
            "welcome_channel": data.get("welcome_channel"),
        }
