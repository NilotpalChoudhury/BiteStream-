import { test } from 'node:test'
import assert from 'node:assert/strict'
import { amountProblem, apiError, browserTimeZone, normalizeResponse, validAmount } from '../src/lib/contracts.js'
import { request } from '../src/lib/api.js'

test('moving average consumes the API series and date fields', () => {
  const result = normalizeResponse('/analytics/moving-average?restaurant_id=r', {
    restaurant_id: 'r', series: [{ date: '2026-10-14', daily_revenue: '123.40', moving_avg_7_day: '17.63' }],
  })
  assert.equal(result.items.length, 1)
  assert.equal(result.items[0].revenue_date, '2026-10-14')
  assert.equal(Number(result.items[0].moving_avg_7_day), 17.63)
})

test('summary uses actual materialized-view counts, including an unpopulated snapshot', () => {
  const result = normalizeResponse('/analytics/summary', { restaurants: 12, total_orders: 521, total_revenue: '108200.50', populated: true })
  assert.equal(result.restaurant_count, 12)
  assert.equal(result.order_count, 521)
  assert.equal(result.active_orders, undefined)
  const empty = normalizeResponse('/analytics/summary', { restaurants: 0, total_orders: 0, total_revenue: 0, populated: false })
  assert.equal(empty.populated, false)
  assert.equal(empty.order_count, 0)
})

test('flat review response supplies overall rating, distribution and top tags', () => {
  const result = normalizeResponse('/restaurants/r/reviews/analytics', {
    total_reviews: 3, average_rating: 4, rating_distribution: [{ rating: 4, count: 3 }], top_tags: [{ tag: 'tasty', count: 2 }],
  })
  assert.deepEqual(result.overall_average_rating, [{ average_rating: 4, total_reviews: 3 }])
  assert.equal(result.most_frequent_tags[0].tag, 'tasty')
  assert.equal(result.rating_distribution[0].count, 3)
  const empty = normalizeResponse('/restaurants/r/reviews/analytics', { total_reviews: 0, average_rating: null, rating_distribution: [], top_tags: [] })
  assert.equal(empty.overall_average_rating[0].total_reviews, 0)
})

test('flat driver coordinates and distance_m become map coordinates and metres', () => {
  const result = normalizeResponse('/drivers/nearby?lat=17&lng=78', {
    items: [{ driver_id: 'd', lng: 78.4747, lat: 17.3616, distance_m: 314, active: true }],
  })
  assert.deepEqual(result.items[0].location.coordinates, [78.4747, 17.3616])
  assert.equal(result.items[0].distance_meters, 314)
})

test('named API errors stay actionable without confusing other P0001 rules with insufficient funds', () => {
  assert.match(apiError({ error_code: 'ACTIVE_ORDER_EXISTS', sqlstate: '23505' }).message, /Browse/)
  assert.match(apiError({ error_code: 'INSUFFICIENT_BALANCE' }).message, /top up/)
  assert.match(apiError({ error_code: 'MV_NOT_POPULATED' }).message, /Refresh snapshot/)
  assert.equal(apiError({ error_code: 'DB_RULE_VIOLATION', sqlstate: 'P0001', message: 'A different rule failed.' }).message, 'A different rule failed.')
})

test('checkout accepts valid cents without floating point multiplication errors', () => {
  for (const amount of ['0.01', '0.29', '19.99', '420.00', '99999999.99']) assert.equal(validAmount(amount), true, amount)
  for (const amount of ['', '0', '-1', '1.001', 'NaN', 'Infinity', '100000000', '1e3']) assert.equal(validAmount(amount), false, amount)
})

test('request sends the expected method/body, adapts actual API data and propagates errors', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    if (url.endsWith('/checkout')) return new Response(JSON.stringify({ error_code: 'ACTIVE_ORDER_EXISTS', sqlstate: '23505' }), { status: 409 })
    return new Response(JSON.stringify({ total_orders: 42, restaurants: 7, total_revenue: 900 }))
  })
  assert.equal((await request('/analytics/summary')).order_count, 42)
  await assert.rejects(request('/checkout', { method: 'POST', body: { amount: 19.99 } }), { error_code: 'ACTIVE_ORDER_EXISTS', sqlstate: '23505' })
  assert.equal(calls[1].url, '/api/checkout')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(JSON.parse(calls[1].options.body).amount, 19.99)
})


test('wallet top-up posts to the selected API customer and returns the server credit', async (t) => {
  const controller = new AbortController()
  const credit = { user: { id: 'customer-id', wallet_balance: '545.00' }, audit_entry: { id: 'credit-id', action_type: 'CREDIT', amount_changed: '500.00', balance_after: '545.00' } }
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/users/customer-id/topup')
    assert.equal(options.method, 'POST')
    assert.equal(options.signal, controller.signal)
    assert.equal(options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(options.body), { amount: 500 })
    return new Response(JSON.stringify(credit))
  })
  assert.deepEqual(await request('/users/customer-id/topup', { method: 'POST', body: { amount: 500 }, signal: controller.signal }), credit)
})

test('API connection failure is surfaced without sample data', async (t) => {
  const failure = new TypeError('Connection refused')
  t.mock.method(globalThis, 'fetch', async () => { throw failure })
  await assert.rejects(request('/restaurants'), (error) => {
    assert.match(error.message, /Unable to reach the BiteStream API/)
    assert.equal(error.cause, failure)
    return true
  })
})

test('unreadable API responses are rejected', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Unavailable</html>', { status: 502 }))
  await assert.rejects(request('/orders'), /unreadable response/)
})

test('cancelling a request preserves AbortError', async (t) => {
  const cancellation = new DOMException('Aborted', 'AbortError')
  t.mock.method(globalThis, 'fetch', async () => { throw cancellation })
  await assert.rejects(request('/users'), (error) => error === cancellation)
})

test('an empty API list stays empty', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ items: [], total: 0 })))
  assert.deepEqual(await request('/restaurants'), { items: [], total: 0 })
})

test('amounts that cannot fit DECIMAL(10,2) are rejected in the browser with a reason', () => {
  assert.equal(amountProblem('420.00'), '')
  assert.equal(amountProblem('99999999.99'), '')
  assert.match(amountProblem('100000000'), /too large/)
  assert.match(amountProblem('99999999999'), /too large/)
  assert.match(amountProblem('0'), /greater than zero/)
  assert.match(amountProblem('12.345'), /two decimal places/)
  assert.match(amountProblem(''), /Enter an amount/)
})

test('a top-up is rejected when the new wallet balance would exceed the limit', () => {
  assert.equal(amountProblem('500', { balance: '1000.00' }), '')
  assert.equal(amountProblem('0.01', { balance: '99999999.98' }), '')
  assert.match(amountProblem('0.02', { balance: '99999999.98' }), /above the/)
  assert.match(amountProblem('95000000', { balance: '10000000.00' }), /above the/)
})

test('checkout never pre-checks the wallet balance (the database must report insufficient funds)', () => {
  assert.equal(amountProblem('5000'), '')
})

test('AMOUNT_TOO_LARGE and SQLSTATE 22003 map to a friendly message', () => {
  assert.match(apiError({ error_code: 'AMOUNT_TOO_LARGE', message: 'x' }).message, /too large/)
  assert.match(apiError({ sqlstate: '22003', message: 'numeric field overflow' }).message, /too large/)
})

test('the browser time zone is an IANA name (or empty, so the API falls back to IST)', () => {
  const zone = browserTimeZone()
  assert.equal(typeof zone, 'string')
  if (zone) assert.doesNotThrow(() => new Intl.DateTimeFormat('en', { timeZone: zone }))
})
