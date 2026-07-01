from tradebot.portfolio import Portfolio


def test_buy_then_sell_books_realized_pnl():
    pf = Portfolio(cash=10_000)
    pf.execute("AAPL", 10, price=100)          # buy 10 @ 100 -> cash 9000
    assert pf.cash == 9_000
    assert pf.position("AAPL").qty == 10
    assert pf.position("AAPL").avg_price == 100

    pf.execute("AAPL", -10, price=110)         # sell 10 @ 110 -> +100 pnl
    assert pf.position("AAPL").is_flat
    assert pf.realized_pnl == 100
    assert pf.cash == 10_100
    assert len(pf.trades) == 1 and pf.trades[0].is_win


def test_average_cost_basis_on_scale_in():
    pf = Portfolio(cash=10_000)
    pf.execute("MSFT", 10, price=100)
    pf.execute("MSFT", 10, price=200)
    # avg = (10*100 + 10*200)/20 = 150
    assert pf.position("MSFT").avg_price == 150
    assert pf.position("MSFT").qty == 20


def test_partial_close_keeps_cost_basis():
    pf = Portfolio(cash=10_000)
    pf.execute("NVDA", 10, price=100)
    pf.execute("NVDA", -4, price=130)
    pos = pf.position("NVDA")
    assert pos.qty == 6
    assert pos.avg_price == 100                # basis unchanged on partial close
    assert pf.realized_pnl == (130 - 100) * 4


def test_equity_marks_to_market():
    pf = Portfolio(cash=5_000)
    pf.execute("SPY", 10, price=400)           # cash now 1000, 10 shares
    eq = pf.equity({"SPY": 420})
    assert eq == 1_000 + 10 * 420


def test_short_then_cover_books_pnl():
    pf = Portfolio(cash=10_000)
    pf.execute("TSLA", -10, price=200)         # short 10 @ 200 -> cash +2000
    assert pf.cash == 12_000
    pf.execute("TSLA", 10, price=180)          # cover @ 180 -> profit 200
    assert pf.position("TSLA").is_flat
    assert pf.realized_pnl == 200
