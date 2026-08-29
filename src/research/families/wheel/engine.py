"""The options wheel on NSE stock options, simulated in rupees.

THE STRATEGY, AND WHY IT IS EXPRESSIBLE HERE AT ALL
The wheel is two half-cycles that chase each other. Holding cash, you sell a
cash-secured out-of-the-money put; if it expires worthless you keep the premium
and sell another, and if it finishes in the money you are assigned the shares at
the strike. Holding shares, you sell an out-of-the-money covered call; if it
expires worthless you keep the premium and sell another, and if it finishes in
the money the shares are called away and you are back in cash.

That is a *physical* story from end to end — it is about owning the share, not
about a cash difference. On NSE it only became a real mechanic with compulsory
physical settlement of stock derivatives, complete from the October 2019 expiry;
before that an in-the-money short put paid a cash difference and the seller
never received shares. European exercise (2011) supplies the other half: a short
stock option cannot be assigned before expiry, so "sell it and hold to expiry"
is a decision the seller actually gets to make rather than a hope. The sample
therefore starts 2020-01-01 and every cycle in it lives under one regime.

THE CYCLE CLOCK IS THE EXPIRY CALENDAR, NOT THE MONTH
NSE stock options are monthly only — there is no weekly stock chain to sell.
So the cycle is: at the close of expiry session E(k), write the contract
expiring at E(k+1); hold it to E(k+1) and settle. Positions are opened on the
day the previous ones die, which is both what a wheel operator does and the only
schedule that needs no intra-cycle option marks. That last point is not
convenience. A mid-cycle exit ("buy back at 50% of max profit", the most common
real-world wheel rule) has to be priced off a strike that very often did not
trade that day, and `settle` on an untouched strike is an exchange mark rather
than a fill. Holding to expiry is priced by the *underlying* — which always
trades — so the terminal value of every position in this simulation is a cash
price, not an option mark. Only the entry is an option price.

WHAT IS DELIBERATELY NOT MODELLED
  * **Rolling a tested put.** A real operator rolls down-and-out to avoid
    assignment. Modelling it needs mid-cycle option quotes, which is exactly
    the fill quality this design refuses to assume.
  * **Margin relief.** Every put here is fully cash-secured. A short put on NSE
    posts SPAN+exposure margin far below the strike notional, so a leveraged
    wheel exists — and would scale both the return and the ruin. Cash-secured
    is the version that is comparable to buy-and-hold, because both then commit
    the same rupees to the same downside.
  * **Early close on the underlying leaving F&O.** A held share position whose
    symbol loses its option chain is marked and sold at the next expiry close.

CORPORATE ACTIONS ARE HANDLED, NOT AVOIDED
Strikes are quoted in unadjusted rupees, and 105 corporate actions land on F&O
names inside this sample — several of them 10:1 splits. Left alone, a split
inside a holding cycle compares a pre-split strike against a post-split close
and books a 90% loss that did not happen. NSE's own response to an action is to
divide every strike by the adjustment ratio and multiply the lot by it, leaving
`strike * quantity` untouched, and that is reproduced exactly here from the
`adj_factor` ratio between entry and expiry: an assigned position's share count
and cost basis move the same way. This is not lookahead — an ex-date is public
weeks in advance — but nothing in the *selection* uses it either way.

WHERE THE MONEY ACTUALLY LEAKS, AND WHY ASSIGNMENT IS THE EXPENSIVE PART
Selling the option is cheap: STT on the premium (0.05% → 0.0625% → 0.1% across
the sample) plus exchange and GST, all charged on a premium worth a percent or
two of the notional. Assignment is not. A physically settled contract is
delivered as a stock trade: 0.1% STT on the full contract value, and brokers
charge a punitive physical-settlement brokerage on top — Zerodha's is 0.25% of
the delivered value. Being called away pays it again. So the cost of a wheel is
dominated by how often it is assigned, on the notional, while its revenue is a
premium; `CostModel.physical_settlement_fee` is the single most important number
in this file and is exposed for sensitivity rather than buried.

THE COMPARISON THIS EXISTS TO MAKE
Against buy-and-hold Nifty, and honestly, which means:
  * the wheel's idle cash earns something — a cash-secured put parks the strike
    notional, and in India that collateral can sit in T-bills or a liquid fund
    at roughly the repo rate. Assuming 0% understates the wheel; assuming the
    equity return overstates it. Both bounds are reported.
  * the benchmark is a *total*-return index where it can be. Price-return Nifty
    hands the wheel a free ~1.2%/yr, and a wheel that only wins on that margin
    has not won.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

# RBI repo rate, hand-entered from the published decision dates. It stands in
# for what collateral earns: Indian brokers pay nothing on idle ledger cash, but
# T-bills or a liquid fund can be pledged as margin at a small haircut, so repo
# is the right order of magnitude and slightly conservative against a liquid
# fund. The 0% case is always run beside it, because the gap between them is
# large enough over 6.7 years to decide the answer on its own.
RBI_REPO_PATH: tuple[tuple[str, float], ...] = (
    ("2020-01-01", 0.0515), ("2020-03-27", 0.0440), ("2020-05-22", 0.0400),
    ("2022-05-04", 0.0440), ("2022-06-08", 0.0490), ("2022-08-05", 0.0540),
    ("2022-09-30", 0.0590), ("2022-12-07", 0.0625), ("2023-02-08", 0.0650),
    ("2025-02-07", 0.0625), ("2025-04-09", 0.0600), ("2025-06-06", 0.0550),
    ("2025-12-05", 0.0525),
)

# STT on the sale of an option, as a fraction of premium, by effective date.
STT_OPTION_SALE: tuple[tuple[str, float], ...] = (
    ("2020-01-01", 0.000500),   # 0.05%
    ("2023-04-01", 0.000625),   # 0.0625%, Finance Act 2023
    ("2024-10-01", 0.001000),   # 0.1%
    ("2026-04-01", 0.001500),   # 0.15%, Finance Act 2026
)


def _step(path: tuple[tuple[str, float], ...], stamps: pd.Series) -> np.ndarray:
    """Value of a right-continuous step function at each timestamp."""
    edges = pd.to_datetime([d for d, _ in path])
    values = np.array([v for _, v in path], dtype=float)
    index = np.searchsorted(edges.to_numpy(), pd.to_datetime(stamps).to_numpy(),
                            side="right") - 1
    return values[np.clip(index, 0, len(values) - 1)]


@dataclass(frozen=True)
class CostModel:
    """Every friction, as a fraction of its own base. Defaults are Zerodha's."""

    # --- on the option premium, when writing ---
    # STT is a step function of date, not a constant, and it tripled across
    # this sample. It lives here rather than as a module constant so that a
    # sensitivity run — or a test — can turn it off.
    stt_option_path: tuple[tuple[str, float], ...] = STT_OPTION_SALE
    exchange_option: float = 0.000500       # NSE txn charge on premium
    sebi_fee: float = 0.000001              # ₹10 per crore
    gst: float = 0.18                       # on exchange + sebi + brokerage
    brokerage_per_lot_order: float = 0.0    # ₹ flat; only bites a quantised book

    # --- the spread, which no archive records ---
    # `settle` and `close` are a mark and a last trade. Neither is a fill. This
    # is the fraction of the quoted premium handed to the spread on entry. In a
    # stock-option chain three strikes out it is not small, and the whole result
    # is re-run across a grid of it rather than asserted at one value.
    premium_haircut: float = 0.05

    # --- on the full contract value, when a contract settles physically ---
    stt_delivery: float = 0.001             # 0.1%, charged to both sides
    exchange_delivery: float = 0.0000297
    stamp_on_buy: float = 0.00015
    # Brokers price physical settlement as work, not as a trade. Zerodha: 0.25%
    # of the delivered value. This is the dominant cost of an assigned wheel.
    physical_settlement_fee: float = 0.0025

    def option_sale(self, premium_value: pd.Series | np.ndarray,
                    stamps: pd.Series) -> np.ndarray:
        """Rupee cost of writing options worth `premium_value` in total."""
        stt = _step(self.stt_option_path, stamps)
        variable = self.exchange_option + self.sebi_fee
        return np.asarray(premium_value) * (
            stt + variable + self.gst * variable)

    def physical(self, contract_value: np.ndarray | float,
                 side: str) -> np.ndarray | float:
        """Rupee cost of taking (or making) delivery worth `contract_value`."""
        variable = self.exchange_delivery + self.sebi_fee
        rate = (self.stt_delivery + self.physical_settlement_fee
                + variable + self.gst * variable)
        if side == "buy":
            rate += self.stamp_on_buy
        return contract_value * rate

    def cash_sale(self, value: np.ndarray | float) -> np.ndarray | float:
        """Selling shares in the cash market — no physical-settlement fee."""
        variable = self.exchange_delivery + self.sebi_fee
        return value * (self.stt_delivery + variable + self.gst * variable)


@dataclass(frozen=True)
class WheelConfig:
    """One wheel. Every knob that could be tuned to taste is named here."""

    # Strike selection, in log-moneyness from the entry close. 0.05 is a strike
    # ~5% out. Positive numbers mean "further out of the money" on both legs.
    put_otm: float = 0.05
    call_otm: float = 0.05
    # A classic wheel refuses to sell a call below its assignment cost basis,
    # so it can never be called away at a loss. It also means a deeply
    # underwater position stops earning anything, which is the whole trade-off.
    call_floor_at_basis: bool = False

    # How many names the book runs at once. Each takes an equal share of equity.
    slots: int = 10

    # A guard, not a tuning knob. NSE relists an expiry when it collides with a
    # holiday — June 2023 exists as both the 28th and a phantom 29th — and a
    # naive "nearest expiry ahead" would occasionally write a one-day contract
    # and call it a monthly cycle. Monthly stock expiries are 28 or 35 days
    # apart throughout the sample, so this band excludes nothing real.
    min_days_to_expiry: int = 15
    max_days_to_expiry: int = 45

    # Tradability of the *chosen strike on the entry session*. `contracts` is
    # the only honest bar: `traded_value` on an option row is strike notional,
    # not premium, and `settle` exists for strikes that never traded.
    min_strike_contracts: float = 50.0
    # Liveness of the whole chain for that symbol and expiry.
    min_chain_contracts: float = 500.0

    # Which quoted price stands in for the fill. `settle` is the exchange's
    # daily mark and exists for every strike; `close` is the last trade, which
    # on a strike that met `min_strike_contracts` is a real print but is the
    # last one of the session and may sit on either side of the spread. The
    # study reports both.
    premium_column: str = "settle"

    # If true, liquidity ranking, the reference spot and the eligible strikes
    # come from the preceding trading session. The entry-day tape is used only
    # to require an actual print and to price the fill. This removes the
    # impossible sequence "observe the completed day, then trade at its close".
    lag_selection: bool = False

    # A held name whose symbol has left the option chain entirely is sold into
    # the cash market at the next expiry close rather than held forever.
    exit_stranded: bool = True

    # Collateral yield. "repo" walks RBI_REPO_PATH; a float is a flat rate.
    cash_yield: str | float = "repo"

    # Lot quantisation. None means fractional lots — that measures the edge
    # without the book-size constraint. A rupee figure quantises to whole lots
    # against that starting capital, which is what an account actually faces.
    starting_capital: float = 1.0
    quantise_lots: bool = False

    costs: CostModel = field(default_factory=CostModel)
    start: date | None = None
    end: date | None = None


@dataclass
class PreparedWheelChain:
    """The 80 entry books and contract calendar, cached for repeated runs."""

    pairs: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]
    by_session: dict[pd.Timestamp, pd.DataFrame]
    prior_by_session: dict[pd.Timestamp, pd.DataFrame]
    contract_last: pd.Series


def _annual_to_period(rate: np.ndarray | float, days: float) -> np.ndarray | float:
    return rate * days / 365.0


def _pick_strike(chain: pd.DataFrame, option_type: str, target: float,
                 min_contracts: float, price: str = "settle",
                 floor: float | None = None) -> pd.Series | None:
    """The listed strike nearest `target` that actually traded on entry day."""
    side = chain.loc[(chain["option_type"] == option_type)
                     & (chain["contracts"] >= min_contracts)
                     & (chain[price] > 0)]
    if floor is not None:
        side = side.loc[side["strike"] >= floor]
    if side.empty:
        return None
    return side.iloc[(side["strike"] - target).abs().argmin()]


def _entry_snapshots(chain: pd.DataFrame, min_days: int = 15,
                     max_days: int = 45
                     ) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """(entry, contract expiry, settlement session) triples.

    An entry session is an expiry day: a session on which some contract is
    settling. The target is then the nearest expiry still ahead of it, which on
    an expiry day is next month's contract. The first session of the sample is
    also an entry, so the book starts working immediately instead of idling
    until the first expiry.

    `expiry` in the archive can remain the nominal date when a holiday moves
    the last trading day earlier. The settlement session is therefore the last
    session on which the completed contract appears. Contracts whose nominal
    expiry is beyond the end of the stored tape are incomplete and excluded;
    otherwise the last open cycle would collect premium and silently discard
    its obligation.
    """
    sessions = pd.DatetimeIndex(np.sort(chain["session"].unique()))
    if not len(sessions):
        return []
    last_tape_session = sessions[-1]
    completed = chain.loc[chain["expiry"] <= last_tape_session]
    calendar = (completed.groupby("expiry")["session"].max()
                .sort_index().to_dict())
    entries = sorted(set(pd.Timestamp(s) for s in calendar.values()))
    if sessions[0] not in entries:
        entries.insert(0, sessions[0])

    quoted = chain.groupby("session")["expiry"].unique()
    pairs = []
    for entry in entries:
        ahead = [pd.Timestamp(e) for e in quoted.get(entry, ())
                 if pd.Timestamp(e) in calendar
                 and min_days <= (pd.Timestamp(calendar[pd.Timestamp(e)])
                                  - entry).days <= max_days]
        if ahead:
            contract_expiry = min(ahead)
            pairs.append((entry, contract_expiry,
                          pd.Timestamp(calendar[contract_expiry])))
    return pairs


def prepare(chain: pd.DataFrame, min_days: int = 15,
            max_days: int = 45) -> PreparedWheelChain:
    """Cache the small expiry-entry slice used by every sensitivity run."""
    pairs = _entry_snapshots(chain, min_days, max_days)
    wanted = {entry: expiry for entry, expiry, _ in pairs}
    sessions = list(pd.DatetimeIndex(np.sort(chain["session"].unique())))
    previous = {sessions[index]: sessions[index - 1]
                for index in range(1, len(sessions))}
    wanted_prior = {previous[entry]: (entry, expiry)
                    for entry, expiry, _ in pairs if entry in previous}
    books = {}
    prior_books = {}
    for session, day in chain.groupby("session", sort=False):
        stamp = pd.Timestamp(session)
        expiry = wanted.get(stamp)
        if expiry is not None:
            books[stamp] = day.loc[day["expiry"] == expiry]
        prior_target = wanted_prior.get(stamp)
        if prior_target is not None:
            entry, expiry = prior_target
            prior_books[entry] = day.loc[day["expiry"] == expiry]
    contract_last = chain.groupby(["symbol", "expiry"])["session"].max()
    return PreparedWheelChain(pairs, books, prior_books, contract_last)


def _pick_lagged_strike(selection: pd.DataFrame, execution: pd.DataFrame,
                        option_type: str, target: float,
                        min_contracts: float, price: str,
                        floor: float | None = None) -> pd.Series | None:
    """Choose from yesterday's liquid strikes; fill an actual print today."""
    candidates = selection.loc[
        (selection["option_type"] == option_type)
        & (selection["contracts"] >= min_contracts)
        & (selection[price] > 0)]
    if floor is not None:
        candidates = candidates.loc[candidates["strike"] >= floor]
    traded = execution.loc[
        (execution["option_type"] == option_type)
        & (execution["contracts"] > 0)
        & (execution[price] > 0)]
    if candidates.empty or traded.empty:
        return None
    available = traded.loc[traded["strike"].isin(candidates["strike"])]
    if available.empty:
        return None
    return available.iloc[(available["strike"] - target).abs().argmin()]


def run(chain: pd.DataFrame | PreparedWheelChain, settle_price: pd.DataFrame,
        cfg: WheelConfig | None = None) -> dict[str, pd.DataFrame]:
    """Simulate the wheel and return its trade log and equity curve.

    `chain`   — `option_chain.load()` output.
    `settle_price` — long frame (symbol, session, price[, adj_factor]) of
                *unadjusted* cash closes. Expiry settlement of a stock option is
                decided by the underlying's closing price in the cash market on
                expiry day, so the terminal value of every position here comes
                from this frame and never from an option mark. `adj_factor` is
                the cumulative corporate-action factor (`close = price *
                adj_factor`); its ratio across a cycle restrikes the contract.
    """
    cfg = cfg or WheelConfig()
    if isinstance(chain, PreparedWheelChain):
        tape = chain
    else:
        if cfg.start is not None:
            chain = chain.loc[chain["session"] >= pd.Timestamp(cfg.start)]
        if cfg.end is not None:
            chain = chain.loc[chain["session"] <= pd.Timestamp(cfg.end)]
        tape = prepare(chain, cfg.min_days_to_expiry, cfg.max_days_to_expiry)

    if "adj_factor" not in settle_price.columns:
        settle_price = settle_price.assign(adj_factor=1.0)
    spot = {(r.symbol, r.session): r.price
            for r in settle_price.itertuples(index=False)}
    adj = {(r.symbol, r.session): r.adj_factor
           for r in settle_price.itertuples(index=False)}

    cash = float(cfg.starting_capital)
    positions: dict[str, dict] = {}     # symbol -> {qty, basis}
    trades: list[dict] = []
    curve: list[dict] = []

    pairs = tape.pairs
    by_session = tape.by_session
    contract_last = tape.contract_last

    for entry, contract_expiry, settlement in pairs:
        day = by_session.get(entry)
        if day is None:
            continue
        raw_book = day.loc[day["expiry"] == contract_expiry]
        if raw_book.empty:
            continue
        # A merger or delisting can force one symbol's contracts to expire
        # before the rest of the monthly series while the bhavcopy continues to
        # display the old nominal expiry (HDFC, July 2023). A new wheel leg in
        # such a contract is not comparable to a normal monthly hold, so exclude
        # it. If shares are already held, liquidate them on that forced-expiry
        # session rather than inventing a successor-security conversion.
        early_settlement = {
            symbol: pd.Timestamp(contract_last.loc[(symbol, contract_expiry)])
            for symbol in raw_book["symbol"].unique()
            if pd.Timestamp(contract_last.loc[(symbol, contract_expiry)])
            < settlement
        }
        book = raw_book.loc[~raw_book["symbol"].isin(early_settlement)]
        if book.empty and not positions:
            continue
        selection_book = (tape.prior_by_session.get(entry, pd.DataFrame())
                          if cfg.lag_selection else book)
        if cfg.lag_selection:
            if selection_book.empty:
                continue
            selection_book = selection_book.loc[
                ~selection_book["symbol"].isin(early_settlement)]
        held_value = sum(
            state["qty"] * spot.get((sym, entry), state["last"])
            for sym, state in positions.items())
        equity = cash + held_value
        if equity <= 0:
            break
        slot_capital = equity / cfg.slots
        days = (settlement - entry).days

        # --- rank the chain by what a wheel actually needs: a live strike ---
        live = selection_book.loc[
            selection_book["contracts"] >= cfg.min_strike_contracts]
        chain_activity = (live.assign(
            premium_turnover=live["contracts"] * live["lot_size"]
            * live[cfg.premium_column])
            .groupby("symbol")["premium_turnover"].sum().sort_values(ascending=False))
        eligible = [s for s in chain_activity.index
                    if chain_activity[s] > 0
                    and selection_book.loc[
                        selection_book["symbol"] == s, "contracts"].sum()
                    >= cfg.min_chain_contracts]

        legs: list[dict] = []

        # ---------- covered calls on what we already own ----------
        for symbol, state in list(positions.items()):
            if symbol in early_settlement:
                legs.append({"symbol": symbol, "kind": "exit",
                             "qty": state["qty"], "strike": np.nan,
                             "premium": 0.0,
                             "ref": spot.get((symbol, entry), state["last"]),
                             "settlement_session": early_settlement[symbol]})
                continue
            sym_chain = book.loc[book["symbol"] == symbol]
            selection_chain = selection_book.loc[
                selection_book["symbol"] == symbol]
            ref = (float(selection_chain["underlying"].iloc[0])
                   if cfg.lag_selection and not selection_chain.empty
                   else spot.get((symbol, entry), state["last"]))
            leg = None
            if not sym_chain.empty and not selection_chain.empty:
                floor = state["basis"] if cfg.call_floor_at_basis else None
                if cfg.lag_selection:
                    leg = _pick_lagged_strike(
                        selection_chain, sym_chain, "CE",
                        ref * np.exp(cfg.call_otm), cfg.min_strike_contracts,
                        cfg.premium_column, floor=floor)
                else:
                    leg = _pick_strike(
                        sym_chain, "CE", ref * np.exp(cfg.call_otm),
                        cfg.min_strike_contracts,
                        price=cfg.premium_column, floor=floor)
            if leg is None:
                # No sellable call. If the symbol has left the option chain
                # altogether the position is stranded and is sold into the cash
                # market at the coming expiry close; if only this strike is
                # missing, the shares are simply held naked for the cycle. Both
                # beat inventing a fill.
                stranded = (cfg.exit_stranded
                            and not (book["symbol"] == symbol).any())
                legs.append({"symbol": symbol,
                             "kind": "exit" if stranded else "hold",
                             "qty": state["qty"], "strike": np.nan,
                             "premium": 0.0, "ref": ref})
                continue
            legs.append({"symbol": symbol, "kind": "call", "qty": state["qty"],
                         "strike": float(leg["strike"]),
                         "premium": float(leg[cfg.premium_column]),
                         "lot_size": float(leg["lot_size"]), "ref": ref})

        # ---------- cash-secured puts into the free slots ----------
        free = cfg.slots - len(positions)
        reserved = 0.0
        for symbol in eligible:
            if free <= 0:
                break
            if symbol in positions:
                continue
            sym_chain = book.loc[book["symbol"] == symbol]
            selection_chain = selection_book.loc[
                selection_book["symbol"] == symbol]
            if selection_chain.empty or sym_chain.empty:
                continue
            ref = float(selection_chain["underlying"].iloc[0]
                        if cfg.lag_selection else sym_chain["underlying"].iloc[0])
            if cfg.lag_selection:
                leg = _pick_lagged_strike(
                    selection_chain, sym_chain, "PE",
                    ref * np.exp(-cfg.put_otm), cfg.min_strike_contracts,
                    cfg.premium_column)
            else:
                leg = _pick_strike(
                    sym_chain, "PE", ref * np.exp(-cfg.put_otm),
                    cfg.min_strike_contracts, price=cfg.premium_column)
            if leg is None:
                continue
            strike = float(leg["strike"])
            lot = float(leg["lot_size"])
            if cfg.quantise_lots:
                lots = np.floor(slot_capital / (strike * lot))
                if lots < 1:
                    continue
                qty = lots * lot
            else:
                qty = slot_capital / strike
            # Cash-secured means cash-secured: the strike notional of every
            # open put has to be sitting there simultaneously.
            if reserved + strike * qty > cash + 1e-9:
                continue
            reserved += strike * qty
            legs.append({"symbol": symbol, "kind": "put", "qty": qty,
                         "strike": strike,
                         "premium": float(leg[cfg.premium_column]),
                         "lot_size": lot, "ref": ref})
            free -= 1

        # ---------- collect premium, net of the spread and of costs ----------
        written = [l for l in legs if l["kind"] in ("put", "call")]
        if written:
            gross = np.array([l["premium"] * l["qty"] for l in written])
            net = gross * (1.0 - cfg.costs.premium_haircut)
            fees = cfg.costs.option_sale(net, pd.Series([entry] * len(net)))
            if cfg.quantise_lots and cfg.costs.brokerage_per_lot_order:
                fees = fees + cfg.costs.brokerage_per_lot_order * np.array(
                    [l["qty"] / l["lot_size"] for l in written])
            cash += float((net - fees).sum())
            for leg, n, f in zip(written, net, fees):
                leg["premium_net"] = float(n - f)
        cycle_premium = float(sum(l.get("premium_net", 0.0) for l in legs))

        # ---------- collateral and cash earn the short rate ----------
        rate = (_step(RBI_REPO_PATH, pd.Series([entry]))[0]
                if cfg.cash_yield == "repo" else float(cfg.cash_yield))
        cycle_interest = cash * _annual_to_period(rate, days)
        cash += cycle_interest
        cycle_settlement_fee = 0.0
        shares_before = held_value

        # ---------- settle on the contract's last trading session ----------
        for leg in legs:
            symbol = leg["symbol"]
            leg_settlement = leg.get("settlement_session", settlement)
            terminal = spot.get((symbol, leg_settlement))
            if terminal is None:
                raise RuntimeError(
                    f"missing cash settlement for {symbol} on "
                    f"{leg_settlement.date()} "
                    f"(contract {contract_expiry.date()})")
            # A corporate action between entry and expiry restrikes the
            # contract: NSE divides the strike by the ratio and multiplies the
            # quantity by it, so the obligation `strike * qty` is unchanged and
            # the new strike is comparable to the post-action close.
            ratio = (adj.get((symbol, leg_settlement), 1.0)
                     / adj.get((symbol, entry), 1.0))
            strike = leg.get("strike")
            if strike is not None and np.isfinite(strike):
                strike = strike / ratio
            qty = leg["qty"] * ratio
            if symbol in positions:
                positions[symbol]["qty"] = qty
                positions[symbol]["basis"] /= ratio

            record = {"entry": entry, "expiry": leg_settlement,
                      "contract_expiry": contract_expiry, "symbol": symbol,
                      "kind": leg["kind"], "qty": qty, "strike": strike,
                      "ref": leg["ref"] / ratio, "terminal": terminal,
                      "premium_net": leg.get("premium_net", 0.0),
                      "adj_ratio": ratio,
                      "assigned": False, "days": days}

            if leg["kind"] == "put":
                if terminal < strike:
                    value = strike * qty
                    fee = cfg.costs.physical(value, "buy")
                    cycle_settlement_fee += float(fee)
                    cash -= value + fee
                    positions[symbol] = {"qty": qty, "basis": strike,
                                         "last": terminal}
                    record["assigned"] = True
            elif leg["kind"] == "call":
                if terminal > strike:
                    value = strike * qty
                    fee = cfg.costs.physical(value, "sell")
                    cycle_settlement_fee += float(fee)
                    cash += value - fee
                    positions.pop(symbol, None)
                    record["assigned"] = True
                else:
                    positions[symbol]["last"] = terminal
            elif leg["kind"] == "exit":             # symbol left the chain
                value = terminal * qty
                fee = cfg.costs.cash_sale(value)
                cycle_settlement_fee += float(fee)
                cash += value - fee
                positions.pop(symbol, None)
            else:                                   # held naked for a cycle
                positions[symbol]["last"] = terminal
            trades.append(record)

        held_value = sum(state["qty"] * state["last"]
                         for state in positions.values())
        closing = cash + held_value
        # Attribution. `premium` and `interest` are what the strategy earns;
        # everything else is what the market and the broker take back, and
        # `underlying` is the residual — the P&L of actually owning the shares
        # plus the loss taken at assignment. A wheel that only looks good
        # because `underlying` was positive is a long-equity book wearing a
        # costume, and this column is how that shows up.
        curve.append({"session": settlement, "equity": closing,
                      "cash": cash, "shares": held_value,
                      "positions": len(positions), "days": days,
                      "written": len(written),
                      "early_expiry_exclusions": len(early_settlement),
                      "premium": cycle_premium, "interest": cycle_interest,
                      "settlement_fee": cycle_settlement_fee,
                      "underlying": closing - equity - cycle_premium
                      - cycle_interest + cycle_settlement_fee})

    return {"trades": pd.DataFrame(trades), "curve": pd.DataFrame(curve)}


__all__ = ["CostModel", "PreparedWheelChain", "RBI_REPO_PATH",
           "STT_OPTION_SALE", "WheelConfig", "prepare", "run"]
