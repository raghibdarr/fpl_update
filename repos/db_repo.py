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
        # legacy v1 table without subscribe_ts
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_subscriptions (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER
            )
        ''')
        # v2 table with subscribe_ts (epoch seconds)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_subscriptions_v2 (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                subscribe_ts INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_seen_events (
                fixture_id INTEGER,
                stat TEXT,
                element INTEGER,
                count INTEGER,
                PRIMARY KEY (fixture_id, stat, element)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_defcon_sent (
                fixture_id INTEGER,
                team_id INTEGER,
                sent INTEGER,
                PRIMARY KEY (fixture_id, team_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_dc (
                fixture_id INTEGER,
                element INTEGER,
                count INTEGER,
                hit_sent INTEGER,
                PRIMARY KEY (fixture_id, element)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_fixture_flags (
                fixture_id INTEGER PRIMARY KEY,
                finished_sent INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS live_bonus_sent (
                guild_id INTEGER,
                fixture_id INTEGER,
                sent INTEGER,
                PRIMARY KEY (guild_id, fixture_id)
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


# Live subscriptions
async def upsert_live_subscription(guild_id: int, channel_id: int, subscribe_ts: int | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        # write into v2
        await db.execute('INSERT OR REPLACE INTO live_subscriptions_v2 (guild_id, channel_id, subscribe_ts) VALUES (?, ?, ?)', (guild_id, channel_id, subscribe_ts or 0))
        await db.commit()


async def remove_live_subscription(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM live_subscriptions WHERE guild_id = ?', (guild_id,))
        await db.commit()


async def get_live_subscription_channel(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # prefer v2
        async with db.execute('SELECT channel_id FROM live_subscriptions_v2 WHERE guild_id = ?', (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
        async with db.execute('SELECT channel_id FROM live_subscriptions WHERE guild_id = ?', (guild_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_all_live_subscriptions():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT guild_id, channel_id, subscribe_ts FROM live_subscriptions_v2') as cursor:
            rows = await cursor.fetchall()
        if rows:
            return rows
        # fallback to legacy table with no timestamp
        async with db.execute('SELECT guild_id, channel_id FROM live_subscriptions') as cursor:
            rows2 = await cursor.fetchall()
            return [(g, c, 0) for (g, c) in rows2]


# Seen counts per fixture/stat/element
async def get_seen_count(fixture_id: int, stat: str, element: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT count FROM live_seen_events WHERE fixture_id = ? AND stat = ? AND element = ?', (fixture_id, stat, element)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_seen_count(fixture_id: int, stat: str, element: int, count: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO live_seen_events (fixture_id, stat, element, count) VALUES (?, ?, ?, ?)', (fixture_id, stat, element, count))
        await db.commit()


# Defcon per element rows
async def get_dc_row(fixture_id: int, element: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT count, hit_sent FROM live_dc WHERE fixture_id = ? AND element = ?', (fixture_id, element)) as cursor:
            row = await cursor.fetchone()
            return row


async def upsert_dc_row(fixture_id: int, element: int, count: int, hit_sent: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO live_dc (fixture_id, element, count, hit_sent) VALUES (?, ?, ?, ?)', (fixture_id, element, count, 1 if hit_sent else 0))
        await db.commit()


# Clean sheet defcon sent flags kept from earlier; not used now for DC but preserved
async def get_defcon_sent(fixture_id: int, team_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT sent FROM live_defcon_sent WHERE fixture_id = ? AND team_id = ?', (fixture_id, team_id)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def set_defcon_sent(fixture_id: int, team_id: int, sent: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO live_defcon_sent (fixture_id, team_id, sent) VALUES (?, ?, ?)', (fixture_id, team_id, 1 if sent else 0))
        await db.commit()


# Finished fixture bonus flag
async def get_finished_sent(fixture_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT finished_sent FROM live_fixture_flags WHERE fixture_id = ?', (fixture_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def set_finished_sent(fixture_id: int, sent: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO live_fixture_flags (fixture_id, finished_sent) VALUES (?, ?)', (fixture_id, 1 if sent else 0))
        await db.commit()


# Per-guild bonus sent flags
async def get_bonus_sent(guild_id: int, fixture_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT sent FROM live_bonus_sent WHERE guild_id = ? AND fixture_id = ?', (guild_id, fixture_id)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def set_bonus_sent(guild_id: int, fixture_id: int, sent: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO live_bonus_sent (guild_id, fixture_id, sent) VALUES (?, ?, ?)', (guild_id, fixture_id, 1 if sent else 0))
        await db.commit()
