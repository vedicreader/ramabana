"""The voiceless register for the prose that ships with code, adapted from Answer.AI's write_docs.

Read this before writing the prose that ships with code: docstrings, code comments, READMEs, API and reference docs, changelogs, PR descriptions, commit messages, and messages to a colleague. The register is GOV.UK/GDS house style with ASD-STE100's discipline. Very plain, very direct, no author's voice. Narrative prose has an author on the page; reference prose has only the contract. For blog posts, essays and announcements read `write_prose` instead.

Here is a passage from a design doc, written in this register:

> `GatewayKernel` ties the three lower layers together. The ready-wait runs once per kernel, in `start`.[1][3] `watch` polls the process and the heartbeat. A process that dies unexpectedly broadcasts the synthesized `dead` status.[1] Three missed heartbeats[4] mark the kernel `unresponsive` in its model, with the next echo clearing the mark.
>
> The gateway never kills an unresponsive kernel.[2] A kernel becomes `dead` only when its process exits.[2] `restart` terminates and respawns with fresh ports in a new process. Clients see `restarting`, then `starting` once the new kernel is ready.[5]

Write like that. Each sentence states one fact and stops. Each guarantee is its own sentence. The negative guarantee is stated too: what the gateway never does. Every status is named by its real identifier. Sentences this uniform would read as monotone in an essay. In reference prose they are correct. Readers scan, take the fact they came for, and leave.

Here is the same passage before editing:

> This section describes how `GatewayKernel` manages the kernel lifecycle.[13] `GatewayKernel` ties the three lower layers together, and its `start` is the only place the ready-wait runs: once per kernel, ever.[1][3] The core mechanism: `watch`.[15] It isn't just a poller - it's the liveness authority.[16] Furthermore,[19] it polls the process and the heartbeat: a process that dies unexpectedly broadcasts the synthesized `dead` status, and three missed beats[4] mark the kernel `unresponsive` in its model.[1] The distinction is worth being precise about.[21] That marking is observational only - only process exit means dead -[2] and it clears itself on the next echo. So what does `restart` actually do?[18] It terminates and respawns; the kernel gains fresh ports, fresh channels, and a fresh interpreter via the new process,[20][23] so the channel set is rebuilt[6] and clients simply[3] see `restarting` then a fresh welcome-backed ready kernel.[5]

Do NOT write like that. Nothing in it is false. In a blog post it might pass. As reference prose it fails. Each sentence carries several facts. The key guarantee is an aside. The final state gets a flourish instead of its name. The opener announces the section instead of starting it. A question delays a fact the reader came for.

The numbers refer to the [bracketed] markers in both passages. Where a number appears in each, the pair is the failing and the working version of the same thing.

1. Splices: clauses joined with em dashes, semicolons, colons, ", and", or ", which". One idea per sentence, then end it. In narrative prose an occasional join earns its place. Here none does.
2. Contract by aside: the rule the reader most needs, implied by an aside, a contrast or a parenthetical. "That marking is observational only" implies the guarantee. "The gateway never kills an unresponsive kernel" states it. Give every guarantee its own sentence. State the negative space too. What the system never does is as much of the contract as what it does.
3. Emphasis devices: "ever", "simply", "just", "the only place", bold, italics. Position is the only emphasis mechanism in reference prose. Put the key fact first in its sentence, and the key sentence first in its paragraph. Delete the intensifiers.
4. Elegant variation: "the heartbeat" becoming "beats" a sentence later. One concept, one name, every time it appears, however repetitive it feels. Never reuse one word for two concepts either. This is STE's one-meaning-per-term.
5. Flourish over identifier: "a fresh welcome-backed ready kernel" where the real status is `starting`. Name the actual identifier, state, value or number. The reader will grep for it, test against it, and see it in logs.
6. Consequence glue: a clause joined by ", so". The consequence is usually restatement, internal detail the reader does not need, or a link that does not hold. Delete it, or give a real consequence its own sentence.
7. Hedging: "may", "might", "potentially", "in some cases", "should generally". A contract that hedges is not a contract. State what the code does. Where behaviour is unspecified or untested, say so outright: "behaviour with concurrent writers is undefined", "not benchmarked".
8. Noting fillers: "note that", "it's worth noting", "importantly", "keep in mind". If the fact matters, state it plainly and early. Delete the filler every time.
9. Restatement: a heading repeated by its section's first line, a lead sentence summarizing the paragraph it starts, a closing line summarizing the section. State each fact once, in its best position, and stop. Summaries earn their place at document scale only, and a README's first paragraph is one.
10. Justification rider: a fact with a benefit clause attached. "kind-sorted so a collector stays legal wherever it came from". The rider argues for the fact instead of stating it. Reference prose states the contract. Rationale lives in design docs and narrative prose; in this repo, in `docs/`.
11. Decorative verbs: a verb chosen for texture instead of the plain word for the event. ids "ride" in rows, a note "lands" in the output. Ask whether you would say the verb at a whiteboard. An artifact subject is fine when the artifact really acts ("`watch` polls the process"). Its verb still has to be the plain one.
12. Audience misjudged, in either direction: explaining what every reader of the doc already knows ("the README documents the package"), or dropping a local coinage without definition. Name the audience. Cut what they know. Define your own coinages at first use. Established external terms of art may stay, because they can be looked up. A coinage cannot.
13. Throat-clearing: an opener that announces the document instead of starting it. "This section describes...", "The purpose of this document is...". Delete it. The first sentence states the first fact.
14. Today's-world opener: "In today's fast-moving AI landscape...". The README form of throat-clearing, with marketing attached. Start with what the package does.
15. Announce-then-deliver: a label and a colon in place of a sentence. "The core mechanism: `watch`.", "The fix: retry on timeout." The label is scaffolding. Write the sentence: "Retrying on timeout fixes it."
16. Not-X-but-Y: "isn't just a poller - it's the liveness authority", "not X, but Y". State what the thing is, directly. Restructure every time.
17. Teaser pivot: "but here's where it gets interesting", "the real story is". A contrast flourish that withholds a fact to build suspense. Reference prose has no suspense. State the facts in order.
18. Rhetorical questions: "So what does `restart` actually do?". Never ask the reader questions, in headings or in prose. Turn each question into the statement it delays. GDS bans FAQ pages on the same principle.
19. Filler transitions: "Furthermore", "Moreover", "Additionally", "In conclusion", "When it comes to". Use "and", "also", or start with the subject.
20. Forced symmetry: three parallel adjectives ("fresh ports, fresh channels, and a fresh interpreter"), three pros and three cons, sections padded to equal length, list items forced into one grammatical mould. Let the material set the count. Treat any list of exactly three as suspect.
21. Appraisal preamble: a clause that appraises the content it introduces. "the distinction is worth being precise about", "the key point is", "crucially". Deliver the fact. Never advertise it.
22. Artifact-as-agent: "this PR introduces", "the change enables", "the design lets you". A person did the deed. Name the doer ("I added retry logic"), or state the resulting behaviour ("`connect` now retries").
23. Recipient-as-subject: the beneficiary promoted to subject, with "gets"/"gains"/"receives" and the doer demoted to a "via"/"through" phrase. "the kernel gains fresh ports via the new process". Name the doer and the deed, or state the new state: "the new process listens on fresh ports".
24. Decoration: emoji, decorative unicode and ornamental symbols. Use ASCII: "->", not an arrow glyph; words, not emoji.
25. Over-structuring: headings, tables or bullets imposed on a document that fits on a screen. Headings are navigation. A short document needs none. Bullets carry parallel facts, never prose chopped into fragments.
26. False depth: restating the problem in fancier words, listing obvious considerations, concluding "it depends". Depth is specifics: identifiers, numbers, edge cases, failure modes.

Entries 7 to 12, 14, 17, 22 and 24 to 26 are tells the passage pair is too short to show.

Instructions address the reader as "you", in the imperative: "Run the tests", not "The tests should be run". Prefer active voice everywhere. A passive that hides the actor usually hides part of the contract with it.

## Banned words

Always use the plainest word that is still correct: use, not "utilize" or "leverage"; improve, not "enhance" or "optimize" unless something is literally being optimized; complete, not "comprehensive"; strong, not "robust"; help, not "facilitate".

Kill on sight: seamless, streamline, empower, foster, pivotal, "a testament to", realm, landscape (metaphorical), navigate (metaphorical), delve, myriad, plethora, paradigm, synergy, holistic, catalyze, juxtapose, tapestry, embark, endeavor, encompass, multifaceted, elucidate, nuanced (as filler), minted (metaphorical). For "land"/"landed" say what happened: merged, committed, released, appears. For metaphorical "shape"/"shaped" say structure, format, or the actual event. "Invariant" is usually "rule" or "guarantee". Compounds in "-bearing", such as load-bearing, have plainer forms.

## Doc types

- Docstrings: the first line states what the function does, and for most functions it is the whole docstring. Parameter detail goes in docments, never repeated in prose. State inputs, outputs, errors raised and guarantees. Never restate the signature.
- Code comments: only a constraint the code cannot show, per `coding_patterns`. Almost never.
- READMEs: read like docstrings, not like blogs. The first paragraph says what the package does and for whom. Then install, then a minimal example. No journey, no sales language.
- API docs and changelogs: the contract or the change, one entry per behaviour. Rationale goes in design docs.
- PR descriptions and commit messages: lead with the behaviour change, name who did what, and give reviewers what they need to judge the diff.
- Messages to a colleague: the answer first, support after. No softening preamble, no closing offer of further help.

## Summaries

A summary of a conversation, a diff, a review thread or a paper has to say what is now true. It does not shorten the source in the source's own order. Write from the situation the source describes. Six failures cover nearly all bad summaries.

- Walking the source: reporting turn by turn, file by file, section by section. Order by subject instead. The reader never needed to know when something was said.
- Topics without content: "we discussed the migration", "this PR refactors the auth module". A sentence that could have been written before reading the source says nothing about it. Cash every topic out in specifics or drop it.
- Pointers to nowhere: "the approach discussed earlier", "the second reviewer's concern". Every reference has to resolve inside the summary itself.
- Claims with no owner: the reader cannot tell a fact from someone's position from your own inference. Give every claim its owner, name people rather than anonymizing them, and mark your inferences as yours.
- No status and no why: a thread reported without its current state, or a conclusion kept while the reason that supports it is dropped. State means decided, dropped or still open; merged, blocked or awaiting review. Gathering the reasons scattered across a long source is most of the work of summarizing, which is why lazy summaries lose them first.
- Space by bulk and buried lede: length tracks the size of the source material instead of how much it changed the situation, and the biggest change arrives last because that is where the source got to it. Weight by importance. Put the largest change first.

A summary has to still work a week later with the source gone. Naming what the source introduced is part of that; reciting background the reader already holds is not.

Never hard-wrap prose. Write each paragraph as one continuous line and let the display soft-wrap it. Put code symbols in backticks: function names, parameters, file paths, module and package names, and literal syntax.

To have a draft checked, send these rules and the draft to a subagent with `delegate_parallel`. Name the audience, so tell 12 can be judged. Ask for flagged spans rather than a rewrite. Only do this when the user asks for a docs check.

Docs: https://vedicreader.github.io/ramabana/write_docs.html.md"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/15_write_docs.ipynb.

# %% auto #0
__all__ = []

# %% ../nbs/15_write_docs.ipynb #f65b9b71
__all__ = []
