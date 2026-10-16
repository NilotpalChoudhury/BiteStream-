# Users

BiteStream has three kinds of users. There is no login: the **Customer** switcher in the header
picks the customer the app acts as, so every workflow can be demonstrated with any seeded user.

## 1. Customer

Orders food and pays from a prepaid wallet.

- Find a restaurant, see its menu and what other guests say about it.
- Place an order paid from the wallet, and see the balance before and after.
- Understand straight away why an order failed: not enough balance, or an order already in
  progress (only one active order is allowed at a time).
- Top up the wallet when the balance is too low.
- Check the wallet history: every credit and debit with the balance after it, filtered by date.

**Screens:** Browse, Place an order, Wallet audit, Reviews & menus.

## 2. Restaurant manager

Runs one or more restaurants and watches how they perform.

- See revenue from completed (delivered) orders and its 7-day moving average over time.
- Compare restaurants in a revenue ranking (equal totals share a rank).
- Read the summary numbers and refresh them on demand, knowing when they were last refreshed.
- Understand guest feedback: rating distribution, most frequent review tags, average rating.
- See the menu exactly as customers see it.

**Screens:** Revenue analytics, Reviews & menus, Browse.

## 3. Operations / dispatcher

Keeps deliveries moving.

- Find the nearest active drivers within 5 km of a restaurant or any chosen point, updated live.
- Move an order through its statuses: Preparing → Delivering → Delivered. Delivering an order
  frees the customer to place the next one.

**Screens:** Live drivers, Browse (Orders).

## Users × screens

| Screen | Customer | Restaurant manager | Operations |
|---|:---:|:---:|:---:|
| Browse | ✓ | ✓ | ✓ |
| Place an order | ✓ | | |
| Wallet audit | ✓ | | |
| Revenue analytics | | ✓ | |
| Live drivers | | | ✓ |
| Reviews & menus | ✓ | ✓ | |

The sidebar follows this split: **Workspace** (customer tasks) and **Operations**.
