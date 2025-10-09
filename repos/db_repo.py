import aiosqlite

DB_PATH = 'fpl_users.db'


async def setup_database():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id INTEGER PRIMARY KEY,
                fpl_id INTEGER,
                team_name TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS leagues (
                guild_id INTEGER PRIMARY KEY,
                league_id INTEGER
            )
        ''')
        await db.commit()


async def upsert_user(discord_id: int, fpl_id: int, team_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR REPLACE INTO users (discord_id, fpl_id, team_name)
            VALUES (?, ?, ?)
        ''', (discord_id, fpl_id, team_name))
        await db.commit()


async def get_user_by_discord_id(discord_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT fpl_id, team_name FROM users WHERE discord_id = ?', (discord_id,)) as cursor:
            return await cursor.fetchone()


async def upsert_league(guild_id: int, league_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO leagues (guild_id, league_id) VALUES (?, ?)', (guild_id, league_id))
        await db.commit()


async def get_league_id_for_guild(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT league_id FROM leagues WHERE guild_id = ?', (guild_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None