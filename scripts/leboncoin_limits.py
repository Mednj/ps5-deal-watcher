"""Shared limits for the browser, client and monitoring."""
MAX_PAGES = 5
MAX_QUERIES = 4

def browser_budget(queries=MAX_QUERIES, pages=MAX_PAGES):
    # Launch/cleanup allowance plus bounded navigation and inspection per page.
    return 60 + queries * pages * 2 * 40

def client_budget(queries=MAX_QUERIES, pages=MAX_PAGES):
    return browser_budget(queries, pages) + 60

CHECK_BUDGET = client_budget() + 30
