"""Backend-only operator CLI for manual reconciliation of unsettled PayPal deposits.

Usage:
    python scripts/reconcile_deposits.py [--deposit-id <uuid>]
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEMO_USER_ID
from database import SessionLocal
from paypal_service import get_default_paypal_client
from wallet_service import reconcile_unsettled_deposits


def main():
    parser = argparse.ArgumentParser(description="Reconcile unsettled PayPal deposits for TradePoint")
    parser.add_argument("--deposit-id", help="Optional specific deposit ID to reconcile", default=None)
    parser.add_argument("--account-id", help="Target account ID", default=DEMO_USER_ID)
    args = parser.parse_args()

    paypal_client = get_default_paypal_client()

    with SessionLocal() as session:
        print(f"Starting reconciliation for account: {args.account_id}")
        if args.deposit_id:
            print(f"Targeting single deposit: {args.deposit_id}")

        results = reconcile_unsettled_deposits(
            session=session,
            paypal_client=paypal_client,
            account_id=args.account_id,
            deposit_id=args.deposit_id
        )

        if not results:
            print("No unsettled deposits in recoverable state found.")
            return

        print(f"Reconciled {len(results)} deposit(s):")
        for dep in results:
            credit = f"{dep.wallet_credit_amount:.2f} INR" if dep.wallet_credit_amount is not None else "None"
            print(f"  - Deposit {dep.deposit_id} (Order {dep.paypal_order_id}): status={dep.status}, credited={credit}, code={dep.failure_code}")


if __name__ == "__main__":
    main()

