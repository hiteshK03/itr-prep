"""Building the Schedule FA JSON the ITD Excel utility will ingest.

Every field name, spelling and type in here was read out of the utility's own VBA and the
official JSON schema. docs/VERIFIED_FINDINGS.md records the line numbers. Two things in
particular look like bugs and are not:

  - "BENIFICIARY" is misspelled in the ITD schema enum and compared as that literal string
    in the VBA. Correcting the spelling breaks both validation and the import.
  - CountryCodeExcludingIndia is a STRING ("2"), not the integer 2. The schema enum
    contains only strings.
"""

from __future__ import annotations

import json
import textwrap

from .models import Account, Issuer
from .positions import FaRow, YearTotals

USA_COUNTRY_CODE = "2"
USA_COUNTRY_NAME = "UNITED STATES OF AMERICA"

FORMAT_ITR = "itr"
FORMAT_PREFILL = "prefill"
FORMATS = (FORMAT_ITR, FORMAT_PREFILL)

# NatureOfAmount enum for Table A2, from the schema:
# I=Interest D=Dividend S=Sale/redemption proceeds O=Other N=No amount paid/credited
NATURE_DIVIDEND = "D"
NATURE_PROCEEDS = "S"
NATURE_NONE = "N"


def build_a3_rows(rows: list[FaRow], issuers: dict[str, Issuer]) -> list[dict]:
    """Table A3 -- DtlsForeignEquityDebtInterest.

    The entity described here is the issuing COMPANY (CSCO, Microsoft, the ETF), never the
    broker. The broker belongs in Table A2.
    """
    out = []
    for row in sorted(rows, key=lambda r: (r.ticker, r.acquire_date, r.lot_id)):
        issuer = issuers[row.ticker]
        out.append({
            "CountryName": issuer.country_name,
            # String, not int -- the schema's enum is all strings.
            "CountryCodeExcludingIndia": str(issuer.country_code),
            "NameOfEntity": issuer.entity_name,
            "AddressOfEntity": issuer.entity_address,
            "ZipCode": issuer.entity_zip,
            "NatureOfEntity": issuer.entity_nature,
            # ISO in JSON; the utility's VBA reformats it to DD/MM/YYYY on import.
            "InterestAcquiringDate": row.acquire_date.isoformat(),
            "InitialValOfInvstmnt": row.initial_value_inr,
            "PeakBalanceDuringPeriod": row.peak_value_inr,
            "ClosingBalance": row.closing_value_inr,
            "TotGrossAmtPaidCredited": row.gross_credited_inr,
            "TotGrossProceeds": row.gross_proceeds_inr,
        })
    return out


def build_a2_rows(
    rows: list[FaRow],
    accounts: dict[str, Account],
    year: int,
    cash: dict | None = None,
) -> list[dict]:
    """Table A2 -- DtlsForeignCustodialAcc, one row per foreign broker account.

    Peak and closing balances for the account are taken as the sum of the peak/closing
    values of the holdings inside it, plus any uninvested cash supplied in
    cash_balances.csv. That slightly overstates the account peak, because the individual
    holdings do not necessarily peak on the same day; it is the conservative direction,
    and Table A2's own instruction is a peak balance for the account rather than a
    same-day snapshot.

    Cash has to be supplied rather than derived: wire transfers in and out never appear in
    a trade export, so the transaction rows cannot reconstruct a cash balance.
    """
    cash = cash or {}
    per_account: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = per_account.setdefault(
            row.account_id,
            {"peak": 0, "closing": 0, "dividends": 0, "proceeds": 0},
        )
        bucket["peak"] += row.peak_value_inr
        bucket["closing"] += row.closing_value_inr
        bucket["dividends"] += row.gross_credited_inr
        bucket["proceeds"] += row.gross_proceeds_inr

    # An account can hold cash and no securities -- a fully-exited account still has to be
    # reported if it existed during the year -- so cash alone is enough to create a row.
    for account_id in cash:
        per_account.setdefault(
            account_id, {"peak": 0, "closing": 0, "dividends": 0, "proceeds": 0}
        )

    for account_id, value in cash.items():
        bucket = per_account[account_id]
        bucket["peak"] += value.peak_inr
        bucket["closing"] += value.closing_inr

    out = []
    for account_id in sorted(per_account):
        account = accounts[account_id]
        totals = per_account[account_id]
        # A2 gives one amount and one nature for the whole account, but a brokerage
        # account can credit both dividends and sale proceeds in the same year. The
        # amount reported is therefore the TOTAL credited -- the field asks for the gross
        # amount paid or credited, and reporting only one component would understate it --
        # while the nature declares whichever component was larger.
        gross = totals["dividends"] + totals["proceeds"]
        if gross <= 0:
            nature = NATURE_NONE
        elif totals["dividends"] >= totals["proceeds"]:
            nature = NATURE_DIVIDEND
        else:
            nature = NATURE_PROCEEDS
        out.append({
            "CountryName": account.country_name,
            "CountryCodeExcludingIndia": str(account.country_code),
            "FinancialInstName": account.institution_name,
            "FinancialInstAddress": account.institution_address,
            "ZipCode": account.institution_zip,
            "AccountNumber": account.account_number,
            # "BENIFICIARY" is misspelled in the official schema on purpose. Do not fix.
            "Status": account.status,
            "AccOpenDate": account.account_open_date or f"{year}-01-01",
            "PeakBalanceDuringPeriod": totals["peak"],
            "ClosingBalance": totals["closing"],
            # Schema sets minimum 0 for this one field, unlike the A3 money fields.
            "GrossAmtPaidCredited": max(0, gross),
            "NatureOfAmount": nature,
        })
    return out


def build_schedule_fa(
    rows: list[FaRow],
    issuers: dict[str, Issuer],
    accounts: dict[str, Account],
    year: int,
    include_a2: bool = True,
    cash: dict | None = None,
) -> dict:
    schedule: dict[str, list[dict]] = {
        "DtlsForeignEquityDebtInterest": build_a3_rows(rows, issuers)
    }
    if include_a2:
        schedule["DtlsForeignCustodialAcc"] = build_a2_rows(rows, accounts, year, cash)
    return schedule


def wrap_itr(schedule_fa: dict, merge_into: dict | None = None) -> dict:
    """Wrap in the ITR.ITR2 envelope that `Sub ImportJson()` expects.

    When `merge_into` is given (the user's own prefill or utility-generated JSON), the
    Schedule FA is injected into that document instead, so a single import restores
    everything rather than leaving other schedules to be re-entered.
    """
    if merge_into is not None:
        document = json.loads(json.dumps(merge_into))  # don't mutate the caller's dict
        itr = document.setdefault("ITR", {})
        itr2 = itr.setdefault("ITR2", {})
        itr2["ScheduleFA"] = schedule_fa
        return document
    return {"ITR": {"ITR2": {"ScheduleFA": schedule_fa}}}


def to_prefill_format(schedule_fa: dict) -> dict:
    """The camelCase shape that `Sub ImportPrefill()` reads.

    Different entry point, different key casing, and the ITD's own typo in the Table A1
    key ("detailsForiegnBank") is preserved because the VBA looks for exactly that.
    """
    key_map = {
        "DetailsForiegnBank": "detailsForiegnBank",
        "DtlsForeignCustodialAcc": "dtlsForeignCustodialAcc",
        "DtlsForeignEquityDebtInterest": "dtlsForeignEquityDebtInterest",
        "DtlsForeignCashValueInsurance": "dtlsForeignCashValueInsurance",
    }
    # The prefill importer also reads different per-row key names for A3/A2.
    a3_field_map = {
        "CountryCodeExcludingIndia": "countryCodeExcludingIndia",
        "NameOfEntity": "nameOfEntity",
        "AddressOfEntity": "addressOfEntity",
        "ZipCode": "zipCode",
        "NatureOfEntity": "natureOfEntity",
        "InterestAcquiringDate": "interestAcquiringDate",
        "InitialValOfInvstmnt": "initialValOfInvstmnt",
        "PeakBalanceDuringPeriod": "peakBalanceDuringPeriod",
        "ClosingBalance": "closingBalance",
        "TotGrossAmtPaidCredited": "totGrossAmtPaidCredited",
        "TotGrossProceeds": "totGrossProceeds",
        "CountryName": "countryName",
    }
    a2_field_map = {
        "CountryCodeExcludingIndia": "countryCodeExcludingIndia",
        "FinancialInstName": "financialInstName",
        "FinancialInstAddress": "financialInstAddress",
        "ZipCode": "zipCode",
        "AccountNumber": "accountNumber",
        "Status": "status",
        "AccOpenDate": "accOpenDate",
        "PeakBalanceDuringPeriod": "peakBalanceDuringPeriod",
        "ClosingBalance": "closingBalance",
        "GrossAmtPaidCredited": "grossAmtPaidCredited",
        "NatureOfAmount": "natureOfAmount",
        "CountryName": "countryName",
    }
    out: dict[str, list[dict]] = {}
    for table, table_rows in schedule_fa.items():
        field_map = (
            a3_field_map if table == "DtlsForeignEquityDebtInterest" else a2_field_map
        )
        out[key_map.get(table, table)] = [
            {field_map.get(k, k): v for k, v in row.items()} for row in table_rows
        ]
    return {"lastFiledITR": {"scheduleFA": out}}


def dump_json(document: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def _foreign_tax_credit_lines(year_rules) -> list[str]:
    """The foreign tax credit deadline paragraph, read out of the rules registry.

    This used to be four hardcoded lines naming Form 67, rule 128(9) and section 139.
    All three were repealed with the Income-tax Act, 1961: from tax year 2026-27 the
    statement is Form No. 44 under rule 76 of the Income-tax Rules, 2026 and the return
    is furnished under section 263. A build for AY 2026-27 still has to print the old
    ones, because that year is still decided under the old Act -- so neither set can be
    a constant here, and both come from the registry for the year being filed.

    The entry was renamed across the change of Act (`form_67_deadline` became
    `foreign_tax_credit_statement_deadline`), which is why both names are tried.
    """
    if year_rules is None:
        return []
    deadline = None
    for key in ("foreign_tax_credit_statement_deadline", "form_67_deadline"):
        if key in year_rules.entries:
            deadline = year_rules.value(key)
            break
    if not isinstance(deadline, dict):
        return []
    form = deadline.get("form", "The foreign tax credit statement")
    rule = deadline.get("rule", "")
    date = deadline.get("date", "")
    sentences = [f"{form} is due on or before {date}" + (f", under {rule}" if rule else "")]
    if deadline.get("conditional_on"):
        sentences.append(f"conditional on {deadline['conditional_on']}")
    paragraph = ", ".join(sentences) + "."
    if deadline.get("updated_return_basis"):
        paragraph += (f" On an UPDATED return the proviso is stricter: {form} must be "
                      f"furnished {deadline['updated_return_basis']}, not after.")
    return textwrap.wrap(paragraph, width=88)


def summarise_other_schedules(
    totals: YearTotals,
    fy_label: str,
    long_term_months: int = 24,
    year_rules=None,
) -> str:
    """Human-readable figures for the schedules Schedule FA does not cover.

    These are not emitted into the JSON: Schedule CG's structure depends on choices this
    tool has no business making (section, indexation, set-off), so the numbers are
    reported for the user to enter or hand to their CA.

    `long_term_months` is the holding period the split was actually computed on, passed
    in from the rules registry so that the two labels here cannot drift away from the
    threshold the arithmetic used.

    `year_rules` is the loaded registry for the year being filed. The foreign tax credit
    paragraph is rendered from it rather than written here, because the form, the rule
    and the deadline all changed with the Income-tax Act, 2025 and this text is printed
    for whichever year the user asked for.
    """
    credit = _foreign_tax_credit_lines(year_rules)
    lines = [
        f"Aggregates for FY {fy_label} (financial year, NOT the Schedule FA calendar year)",
        "",
        "Schedule CG -- foreign shares, to enter as two aggregate blocks:",
        f"  Short term (held <= {long_term_months} months)",
        f"    Full value of consideration : INR {totals.stcg_proceeds_inr:,}",
        f"    Cost of acquisition         : INR {totals.stcg_cost_inr:,}",
        f"    Net short-term gain         : INR {totals.stcg_gain_inr:,}",
        f"  Long term (held > {long_term_months} months)",
        f"    Full value of consideration : INR {totals.ltcg_proceeds_inr:,}",
        f"    Cost of acquisition         : INR {totals.ltcg_cost_inr:,}",
        f"    Net long-term gain          : INR {totals.ltcg_gain_inr:,}",
        "",
        "Schedule OS / FSI / TR and the foreign tax credit statement -- foreign dividends:",
        f"    Gross dividend  : USD {totals.dividends_usd:.2f}  "
        f"= INR {totals.dividends_inr:,}",
        f"    US tax withheld : USD {totals.dividend_tax_withheld_usd:.2f}  "
        f"= INR {totals.dividend_tax_withheld_inr:,}",
        "",
        "The withheld tax is the figure to claim as foreign tax credit in Schedule TR.",
        *credit,
    ]
    return "\n".join(lines)
