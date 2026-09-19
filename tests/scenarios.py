"""Крайние случаи лобби через поддельный Telegram. Запуск: python -m tests.scenarios"""
import asyncio

import tests.simulate as sim


async def main():
    tg = sim.FakeTelegram(); runner = await tg.start(sim.PORT)
    bot = sim.create_bot(); await sim.db.init()
    sim.config.BOT_USERNAME = (await bot.get_me()).username
    sim.manager.setup(bot); dp = sim.build_dispatcher()
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731
    G = sim.GROUP

    # 1. Недостаточно игроков → отмена по таймеру
    sim.config.REGISTRATION_TIME = 1
    await feed(sim.message_update(G, 1, "/game"))
    await feed(sim.message_update(G, 2, "/game"))
    assert "уже идёт" in tg.by_chat[G][-1].text
    await asyncio.sleep(1.5)
    assert "Недостаточно игроков" in tg.by_chat[G][-1].text and G not in sim.manager.by_chat

    # 2. /stop: чужой не может, создатель может
    sim.config.REGISTRATION_TIME = 30
    await feed(sim.message_update(G, 1, "/game"))
    await feed(sim.message_update(G, 5, "/stop"))
    assert "только её создатель" in tg.by_chat[G][-1].text
    tg.admins.add(6)
    await feed(sim.message_update(G, 6, "/begin"))  # админ может, но игроков мало
    assert "минимум" in tg.by_chat[G][-1].text
    await feed(sim.message_update(G, 1, "/extend"))
    assert "продлён" in tg.by_chat[G][-1].text
    await feed(sim.message_update(G, 1, "/stop"))
    assert "остановил" in tg.by_chat[G][-1].text and G not in sim.manager.by_chat

    # 3. Устаревшая ссылка на вход
    await feed(sim.message_update(7, 7, "/start join_deadbeef"))
    assert "закончилась" in tg.by_chat[7][-1].text

    # 4. Один игрок не может быть в двух играх
    sim.config.REGISTRATION_TIME = 30
    await feed(sim.message_update(-2002, 8, "/game"))
    lobby1 = tg.by_chat[-2002][-1]; p1 = sim.buttons(lobby1)[0]["url"].split("start=")[1]
    await feed(sim.message_update(G, 9, "/game"))
    lobby2 = tg.by_chat[G][-1]; p2 = sim.buttons(lobby2)[0]["url"].split("start=")[1]
    await feed(sim.message_update(8, 8, f"/start {p1}"))
    await feed(sim.message_update(8, 8, f"/start {p2}"))
    assert "уже участвуете" in tg.by_chat[8][-1].text

    # 5. Информационные команды
    for cmd in ("/rules", "/roles", "/help", "/stats"):
        await feed(sim.message_update(10, 10, cmd))
    await feed(sim.message_update(G, 10, "/top"))
    texts = [s.text for s in tg.by_chat[10]]
    assert any("Правила" in t for t in texts) and any("Роли" in t for t in texts) and any("Статистика" in t or "ещё не сыграли" in t for t in texts)

    for g in list(sim.manager.by_chat.values()):
        await sim.manager.stop(g)
    await bot.session.close(); await sim.db.close(); await runner.cleanup()
    assert not sim.errors, sim.errors
    print("SCENARIOS OK")


async def run():
    try:
        await main()
    finally:
        await sim.db.close()


asyncio.run(run())
