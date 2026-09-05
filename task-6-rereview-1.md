# Task 6 scoped re-review — fix 1

Reviewed: 2026-08-28  
Scope: previously reported omission of real SDK release inputs from the
N32G452 platform-contamination guard; accuracy of the related Task 7
verification wording; new Critical/Important findings only.  
Reviewed commit: `af377eea3508432eb313643320f8e66201b29622`  
Task 6 review base recorded by the verification document:
`77d78b6face005ec43bc02d67ae18930e72c50fd`.

## Verdict

- **Spec: PASS**
- **Quality: PASS**
- **New Critical/Important findings: none**

The original SDK-input scan omission is **ADDRESSED**.  The guard now derives
SDK inputs from the application `Makefile`, rather than treating the SDK as an
unscanned exclusion.

## Evidence

`Makefile` defines the direct SDK root and selects exactly:

- 15 SDK translation units in `C_SRCS`: `system_n32l40x.c` plus 14 listed
  standard-peripheral driver sources.
- Three SDK include roots in `INCLUDES`: `CMSIS/core`, `CMSIS/device`, and
  `n32l40x_std_periph_driver/inc`.  In this checkout these contain 11, 3, and
  24 `.h` files respectively, for 38 headers.

At `af377ee`, `tools/tests/test_feature_guards.py`:

1. Parses `SDK`, `C_SRCS`, and `INCLUDES`, including Makefile continuations.
2. Selects SDK `.c` files only when they are explicitly listed by `C_SRCS`.
3. Recursively selects headers only below SDK include directories explicitly
   passed with `-I`.
4. Applies the existing case-insensitive `N32G452`/`N32G45x`/`N32G4xx` scan to
   those derived inputs together with the project release inputs.
5. Has a temporary-tree negative regression proving rejection for all three
   forbidden forms, covering both a derived compiled SDK source and a derived
   SDK header.

Fresh verification run:

```
python tools/tests/test_feature_guards.py
test_feature_guards: PASS
```

A direct `rg -i 'n32g(?:452|45x|4xx)'` scan over the same 15 selected SDK
sources and three selected include trees returned no matches.

## Documentation check

`docs/task7-f39-verification.md` accurately describes the current guard and
the observed input set: 15 selected SDK `.c` files, 38 headers under the three
selected SDK include roots, and exclusion of vendor example projects that the
application Makefile neither compiles nor includes.  The claim is appropriately
limited to application-Makefile-selected release production inputs; it does not
incorrectly claim that all vendor-SDK content is scanned.

## Scope notes

This is a narrow guard/documentation re-review.  It does not change the
pre-existing Task 7 release blockers recorded in the verification document,
including the failing repository release guard, the external-Flash host fixture
failure, absent blind-zone write/replay implementation, and outstanding target
hardware/build gates.
