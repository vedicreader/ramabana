---
name: fossick
description: >
  Web search, page fetching, crawling, and browser automation for AI agents.
  Use instead of WebSearch and WebFetch. Covers arxiv, YouTube, GitHub,
  static pages, JS-rendered pages, bot-protected sites, hidden JSON APIs,
  authenticated Chrome sessions, screenshot capture, element annotation, and
  shopping carts (find products, add to cart with verification, fill checkout forms).
triggers:
  - about to call WebSearch or WebFetch
  - user asks to search the web or fetch a URL
  - URL is arxiv.org, youtube.com, youtu.be, or github.com
  - need to scrape, crawl, paginate, or hit a hidden JSON API
  - convert a URL, PDF, or arXiv paper to a notebook
  - screenshot, annotate, or intercept requests on a live page
  - add something to a cart, check out, or fill a shipping/billing form
---

# fossick

Drop-in for `WebSearch`/`WebFetch` — always prefer it.

```python
from fossick import *                              # fetch, crawl, research, find_xhr, replay_xhr, read_*, ...
from fossick.search import search, images, news, videos, google, extract, research  # ddgs + stealth Google + research
from fossick.cdp import cdp_connect, cdp_ws, cdp_cookies, ax_diff, syncy   # browser automation + agent toolkit
from fossick.shop import shop                     # shopping carts: search -> add (verified) -> checkout
```

## Route

```
arxiv URL/ID          -> read_arxiv(id)              # dict; source is 30-100k chars, slice it
YouTube URL           -> read_yt(url)                # metadata + transcript
  download media       -> download_yt(url, format='audio'|'video')
  search               -> search_yt(q, n=10)
GitHub file / repo    -> read_gh_file(url) / read_gh_repo(url, globs=('README*','*.py'))
search query          -> search(q, max_results=10)   # ddgs metasearch, no Docker; dicts: title, href, body
  images/news/videos   -> images(q) | news(q) | videos(q)   # or search(q, category='images'|'news'|'videos')
  real Google ranking  -> google(q, n=10)             # stealth browser; slow, use when you need Google
  read a result URL    -> extract(url) | fetch(url)
question -> answer     -> research(q, n=5)            # search + read top N -> {query, sources, digest} cited markdown
paper title -> DOI    -> lookup_doi(title)
-> notebook           -> url2nb(url) | pdf2nb(url_or_path)
have a URL:
  static               -> fetch(url); to_md(page, sel='main')   # always pass sel
  JS-rendered          -> fetch(url, heavy=True)
  bot-protected        -> fetch(url, stealthy=True)             # slow; only when blocked
  not sure / mixed     -> fetch(url, auto=True)                 # escalates plain->heavy->stealthy->session; winner on page.tier
  behind a login       -> fetch(url, session=True)             # reuses the debug Chrome's logged-in cookies, no login code
  many links           -> crawl(url, follow_sel='a[href]', max_pages=N)   # reuse=True keeps one browser open
  many known URLs      -> fetch_all(urls)
  hidden JSON API      -> find_xhr(url, pattern='*api*') -> paginate_api(...)
  authed hidden API    -> find_xhr(url, session=True) -> replay_xhr(hit.capture)   # via logged-in Chrome
  intercept requests   -> cdp.calls(url, pattern='*api*')
  screenshot           -> pg.collect(save_dir='.', count=1)
  annotate for LLM     -> pg.annotate(save_dir='.')
  interactive / SSO    -> cdp_connect() + pg.snapshot() + pg.fill_form()/pg.act()
shopping cart         -> s = shop(store_url)          # never write selectors for this
  find products        -> s.search(q) | s.products() | s.find(q)   # numbered: {i, title, price, add, qty, oos}
  add one              -> s.add(i_or_title, qty=2)    # VERIFIED: ok=True/False/None + how + before/after
  needs a size         -> s.add(i, variant='9')       # add() returns need='variant' + in-stock variants
  cart / lines         -> s.cart() | s.cart_page()    # cart_page() is what gives you line indexes
  change / remove      -> s.set_qty(line, n) | s.remove(line)
  stuck                -> s.blockers() -> s.dismiss() # cookie banner, login, store/postcode, captcha
  checkout form        -> s.fields() then s.fill(profile)   # fields() first: never guess field names
  one odd field        -> s.fill({'7': 'Large'})     # numeric key = that fields() index
```

## API

| Function | Key params | Returns |
|---|---|---|
| `search(q)` | `category`, `max_results`, `region`, `backend` | list[dict] (`title, href, body`) |
| `images(q)` / `news(q)` / `videos(q)` / `books(q)` | `max_results`, `region` | list[dict] (ddgs-native fields) |
| `google(q)` | `n`, `lang` | list[dict] (`title, href, content`; stealth browser) |
| `extract(url)` | — | list[dict] (page content via ddgs) |
| `lookup_doi(title)` | — | str\|None |
| `fetch(url)` | `sel`, `heavy`, `stealthy`, `session`, `auto`, `method`, `payload` | Page dict (`.tier` when `auto`) |
| `research(q)` | `n`, `engine` ('search'\|'google'), `sel`, `chars` | dict (`query, sources, digest`) |
| `to_md(page)` | `sel`, `multi`, `wrap_tag` | str |
| `crawl(url)` | `follow_sel`, `same_domain`, `max_pages`, `heavy`, `reuse` | list[Page] |
| `fetch_all(urls)` | `sel`, `concurrency`, `auto` | list[Page] |
| `browser_session(stealthy)` | `headless`, `**init` | ctx mgr -> `fetch(url, sel)` func (one warm browser) |
| `find_xhr(url)` | `pattern`, `session`, `port`, `tail` | list[{url, content_type, data, capture}] |
| `replay_xhr(capture)` | `data`, `use_cookies`, `port` | Response (fast authed replay of a captured request) |
| `paginate_api(url)` | `payload`, `page_field`, `results_field`, `max_pages` | list |
| `cdp_cookies(url)` | `port`, `as_dict` | Playwright cookies list (or `{name:value}` dict) |
| `url2nb(url)` / `pdf2nb(src)` | `nb_path` | Path |
| `read_arxiv(url)` | `save_pdf`, `force` | dict (`title authors summary source`) |
| `read_yt(url)` / `search_yt(q)` | `force` / `n` | dict / `L[dict]` |
| `read_gh_repo(url)` / `read_gh_file(url)` | `globs`, `limit` | {path:content} / str |
| `cdp_connect(port)` / `syncy(coro)` | — | CDP / any |
| `cdp_ws(port)` | `headless` | ws debugger URL (for scrapling `cdp_url=`) |
| `cdp.open_page(url)` / `cdp.calls(url, pattern)` | `tail` | Page / dict |
| `pg.snapshot()` | `interactive`, `keep` | str — compact `[#id] role "name"` per element (agent-ready) |
| `pg.fill_form(fields, submit)` | — | post-action `snapshot()`; fills by label, handles `<select>` |
| `pg.act(steps)` | — | dict of `read` results; steps: goto/fill/click/select/wait/read |
| `pg.md(sel)` / `pg.selector()` / `pg.html()` | — | live post-JS page as markdown / Selector / html |
| `pg.click_sel(css)` / `pg.fill_sel(css, t)` / `pg.node_for(css)` | — | CSS -> CDP action / backendNodeId |
| `ax_diff(before, after)` | — | str — what an action changed between two snapshots |
| `pg.ax_tree()` | — | AXTree (has `[#N]` node IDs) |
| `pg.fill_text(id, text)` / `pg.click_and_wait(id)` | — | — |
| `pg.collect(save_dir)` | `count`, `tout`, `every_n` | list |
| `pg.annotate(save_dir)` | — | (img, [{n, role, name, selector}]) |
| `shop(url)` | `port`, `headless` | `Shop` on the persistent debug Chrome |
| `s.search(q)` / `s.products()` / `s.find(q)` | `limit` | list[dict] (`i, title, price, url, add, qty, oos, vid`) |
| `s.add(item)` | `qty`, `variant` | dict (`ok, how, item, before, after`; `need='variant'` when a size is required) |
| `s.cart()` / `s.cart_page()` | `lines` / `url` | dict (`count, subtotal, lines, source`) |
| `s.set_qty(line, n)` / `s.remove(line)` | — | dict (`ok, how, before, after`) |
| `s.fields()` | — | list[dict] (`i, label, autocomplete, type, value, options`) |
| `s.fill(profile)` | `submit`, `confirm` | dict (`filled, failed, unmatched`); refuses payment buttons |
| `s.fill({'7': 'L'})` | — | numeric key = set that `fields()` index (size, colour, delivery window) |
| `s.blockers()` / `s.dismiss()` | — | list[str] / list[str] |

## Non-obvious usage

```python
# hidden JSON API (public)
apis  = find_xhr('https://example.com/shop', pattern='*api*')
items = paginate_api(apis[0]['url'], results_field='items', max_pages=50)

# hidden JSON API behind a login: capture via the authenticated Chrome, then replay fast
hits = find_xhr('https://app.example.com/dashboard', pattern='*api*', session=True)
data = replay_xhr(hits[0].capture).json()     # reuses the browser's cookies

# question -> cited answer in one call
notes = research('best vector databases 2025', n=5)
print(notes['digest'])                         # markdown, one ## section per source

# shopping cart — no selectors, and the add is verified rather than assumed
s = shop('https://members.ceresfairfood.org.au')
s.search('apples')                             # [{'i': 0, 'title': 'Apples Fuji IPM 500g', 'price': 5.5, ...}]
r = s.add('Apples Fuji Organic 500g', qty=2)
r['ok'], r['how']                              # True, 'count'   <- the cart really changed
# ok=None means the page has no cart signal to check (logged out, no badge) — do NOT report success
if r['ok'] is not True: r['blockers'], r['page_error']
s.cart_page()                                  # {'count': 2, 'subtotal': 13.0, 'lines': [...]}

# checkout: read the form, then fill it. fields() is ground truth — labels differ by country
s.fields()                                     # [{'i': 7, 'label': 'Suburb', 'autocomplete': 'address-level2'}, ...]
s.fill(dict(email='sam@example.com', first_name='Sam', last_name='Nguyen',
            address1='12 Smith St', city='Brunswick', state='Victoria', postcode='3056'))

# browser automation — snapshot(), act by label, no manual node IDs
cdp = syncy(cdp_connect())
pg  = syncy(cdp.open_page('https://example.com/login'))
print(syncy(pg.snapshot()))                    # compact, agent-ready; snapshot re-reads the tree for you
print(syncy(pg.fill_form({'Email': 'me@x.com', 'Password': 'pw'}, submit='Sign in')))
# low-level still available: pg.ax_tree() -> pg.fill_text([#N], ...) -> pg.click_and_wait([#N])
```

## CLI

All commands take `--as_json`.

```sh
fossick fetch <url> [--sel css] [--heavy] [--stealthy] [--session] [--auto]
fossick research "<q>" [--n 5] [--google] [--sel css] [--chars 4000]   # search + read -> cited markdown
fossick ax <url> [--port 9223] [--full]                     # compact accessibility snapshot of a live page
fossick crawl <url> [--follow_sel css] [--max_pages N] [--sel css]
fossick search "<q>" [--n 10] [--region us-en] [--google]   # --google: real Google via stealth browser
fossick images "<q>" [--n 20] [--region us-en]
fossick news "<q>" [--n 20] [--region us-en]
fossick videos "<q>" [--n 20] [--region us-en]
fossick lookup-doi "<title>"
fossick read-arxiv <url-or-id> [--source] [--chars 4000] [--force]
fossick read-yt <url> [--force]
fossick search-yt "<q>" [--n 10]
fossick download-yt <url> [--format audio|video] [--save_dir .]
fossick read-gh-file <blob-url>
fossick read-gh-repo <url> [--globs 'README*,*.py'] [--limit N]
fossick url2nb <url> [--path out.ipynb]
fossick pdf2nb <url-or-path> [--path out.ipynb] [--ocr auto|on|off]
fossick find-xhr <url> [--pattern '*api*'] [--session]
fossick paginate-api <url> [--payload '{...}'] [--results_field items] [--max_pages 10]
fossick calls <url> [--pattern '.*'] [--tail 3]
fossick collect <url> [--save_dir .] [--count N] [--every_n N]
fossick annotate <url> [--save_dir .]
fossick shop <url> [--search q] [--add i_or_title] [--qty n] [--variant v] [--cart] [--fields]
                                                # reuses the tab it left open: --search then --add i
fossick install                                 # register SKILL.md + safecmd allowlist
```

## MCP server

`fossick-mcp` exposes the whole toolkit over the Model Context Protocol — every Python/CLI function is an MCP tool, so any MCP client (Claude Code, Claude Desktop, Codex) can drive fossick. The `mcp` package ships with fossick, so a plain install is all you need.

```sh
claude mcp add fossick -- uvx --from fossick fossick-mcp   # Claude Code; uv run fossick-mcp if already a project dep
```

Tools mirror the API: `web_search`/`research`, `fetch_page`/`fetch_pages`/`crawl_site`, `read_arxiv`/`read_youtube`/`search_youtube`/`download_youtube`/`read_github_file`/`read_github_repo`, `url_to_notebook`/`pdf_to_notebook`, `find_hidden_apis`/`replay_capture`/`paginate_api`, `browse`/`page_snapshot`/`page_fill_form`/`page_act`/`page_markdown`/`capture_network` for the persistent logged-in debug Chrome, and `shop_open`/`shop_search`/`shop_products`/`shop_add`/`shop_cart`/`shop_line`/`shop_fields`/`shop_fill`/`shop_dismiss` for shopping carts. stdio by default; `fossick-mcp --http` for Streamable HTTP.

## Gotchas

- `search()`/`images()`/`news()` use ddgs — no Docker, no setup. Direct Google is IP-blocked for plain HTTP, so `google()` uses the stealth browser (slow) for real Google ranking.
- `heavy`/`stealthy`/CDP need Chrome (~10s cold start); `stealthy` is slowest — only when a site actively blocks.
- `session=True` / `find_xhr(session=True)` / `ax` drive a persistent debug Chrome (port 9223), launched **headless** on first use; cookies persist across runs. To log in by hand you need it **headed**, but `headless=` only takes effect at launch — so if a headless one is already running, quit it first, then relaunch: `syncy(cdp.quit()); syncy(cdp_setup(9223, headless=False))` (see *Managing the debug Chrome* in the cdp docs). Root/containers auto-add `--no-sandbox`.
- `snapshot()` beats dumping `ax_tree()` for agents — interactive-only and re-read each call; `fill_form`/`act` take labels, not node IDs.
- Always pass `sel=` to `to_md`/`fetch`/`crawl` — otherwise you get nav/ads.
- `read_arxiv()['source']` is 30-100k chars — slice: `paper['source'][:8000]`.
- `annotate` is interactive — needs a visible browser, not headless pipelines.
- `s.add()` returns `ok=True` only when a cart signal actually moved. `ok=None` means the page exposes
  none to check — report that, never "added". Read `how`, `page_error` and `blockers` before retrying.
- Cart line indexes come from the **cart page**: `s.cart_page()` then `s.set_qty()`/`s.remove()`
  (`shop_line(line, qty)` over MCP — `qty=0` removes).
- Call `s.fields()` before `s.fill()`; label wording is site- and country-specific ("Suburb" vs "City").
- `s.fill(submit=...)` refuses payment-looking buttons unless you also pass `confirm=True`. Don't pass it
  unless the user asked you to place the order.
- Supermarkets (Coles/Woolworths) need a store/suburb and often a login, and block datacentre IPs —
  run them through a debug Chrome on a real machine and set that up by hand once.
