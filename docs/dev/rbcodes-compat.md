# rbcodes on Python 3.12: compatibility spike

*Phase 00, 2026-09-02.* rbcodes `2.4.0` at commit `4499012e77eb3bbb9ca934b5b53909864581d060`
(`rongmon/rbcodes` master, identical to the local read-only checkout). Host: Windows 11 x64.

## Method

1. Copied the checkout to a scratch folder and relaxed `python_requires` in `setup.cfg` from `>=3.9.6,<3.11` to `>=3.10,<3.14`.
2. `uv venv --python 3.12` then `uv pip install .` (setuptools build; `SETUPTOOLS_SCM_PRETEND_VERSION=2.4.0` because the copy has no `.git`).
3. `pytest tests -x` and then the full suite, headless: `MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen`, `--no-cov`.
4. Imported the headless modules the v0.1 packs will use and recorded the active matplotlib backend after each import.
5. Applied `rbcodes-upstream.patch` to the scratch copy, reinstalled, and repeated steps 3 and 4.

## Result in one line

rbcodes **installs and imports on Python 3.12** once the pin is relaxed. **144 of 165 tests pass**; none of the 21
failures is caused by Python 3.12. Seven come from NumPy 2 (`np.trapz` used by the test itself), thirteen from a stale
mock in `rb_setline_test.py`, one from a stale expectation in `test_zfind_adapters.py`.

## Resolved environment (Python 3.12.13, uv 0.11.25)

| Package | Version | | Package | Version |
|---|---|---|---|---|
| numpy | 2.5.2 | | PyQt5 | 5.15.11 |
| scipy | 1.18.1 | | linetools | 0.3.2 |
| astropy | 8.0.1 | | pandas | 3.0.5 |
| matplotlib | 3.11.1 | | photutils | 3.0.0 |
| scikit-learn | 1.9.0 | | emcee / corner | 3.1.6 / 2.3.0 |
| regions | 0.12 | | pytest | 9.1.1 |

Install time from a warm uv cache: 19 s. The `use_scm_version` keyword in `setup.py` is ignored with a warning because
`setuptools_scm` is not in `build-system.requires`; the version then comes from `setup.cfg` (`attr: rbcodes.__version__`).

## Test results per module (unpatched and patched give identical numbers)

| Module | Passed | Failed | Cause of failures |
|---|---|---|---|
| `tests/test_gui/test_zfind_adapters.py` | 32 | 1 | `test_idx_out_of_range_raises` expects `IndexError`; `zfind_to_zgui_z` clamps `idx` instead (stale test) |
| `tests/test_gui/test_zfind_engine_absorption.py` | 31 | 0 | |
| `tests/test_gui/test_zfind_engine_emission.py` | 25 | 0 | |
| `tests/test_gui/test_zfind_io.py` | 37 | 0 | |
| `tests/test_igm/lens_sep_to_kpc_test.py` | 8 | 0 | |
| `tests/test_igm/rb_setline_test.py` | 0 | 13 | tests patch `rbcodes.IGM.rb_setline.resource_filename`, but the module now uses `importlib.resources.files` (stale mock) |
| `tests/test_igm/rb_specbin_test.py` | 11 | 0 | |
| `tests/test_igm/test_compute_EW.py` | 0 | 7 | the test computes its reference with `np.trapz`, removed in NumPy 2.0 (`np.trapezoid`) |
| **Total** | **144** | **21** | |

`pytest tests -x` stops at the first failure (`test_zfind_adapters.py::test_idx_out_of_range_raises`) after 8 passes.

## Headless import check (`MPLBACKEND=Agg`)

| Module | Unpatched | Patched |
|---|---|---|
| `rbcodes`, `rbcodes.IGM.compute_EW`, `rbcodes.IGM.rb_setline`, `rbcodes.IGM.rb_iter_contfit` | OK, backend stays Agg | same |
| `rbcodes.utils.rb_spectrum`, `rbcodes.utils.rb_utility`, `rbcodes.GUIs.zfind.engine` | OK, backend stays Agg | same |
| `rbcodes.IGM.ransac_contfit` | OK but **switches the process to Qt5Agg** (module-level `matplotlib.use`) | OK, backend stays Agg; still Qt5Agg when `MPLBACKEND` is unset |

## Blockers and issues found

1. **`python_requires <3.11`** (blocker for any 3.12 install). Fixed by the patch.
2. **Module-level `matplotlib.use('Qt5Agg')`** in 13 modules, including the non-GUI `rbcodes/IGM/ransac_contfit.py`.
   Importing any of them from a server process forces the Qt backend, which needs PyQt5 and, on Linux, a display.
   The patch guards each call with `if not os.environ.get('MPLBACKEND')`, so headless callers keep their backend and GUI
   users see no change. `rbcodes/GUIs/rb_spec.py:325` calls `matplotlib.use` inside a function and is left as is.
3. **Undeclared optional dependencies.** `rbcodes.IGM.LLSVoigtFitter` imports `rbvfit` (not on PyPI) and the LLS examples
   import `h5py`; `rbcodes.utils.rb_spectrum` imports `h5py` in a guarded block. The patch declares them as the extra
   `rbcodes[lls]`. No module imports PyWavelets, so no `wavelets` extra was added despite the design's expectation.
4. **NumPy 2 removals** (not Python-version specific, but every fresh 3.12 environment resolves NumPy 2):
   `np.trapz` in `halo/rb_nfw.py`, `lensing/lens_ang_sep.py`, and `tests/test_igm/test_compute_EW.py`;
   `np.int` / `np.str` in `GUIs/guess_abs_line_vel_gui.py` and `GUIs/PlotSpec_Integrated.py`. Not touched by the patch;
   listed for an upstream follow-up. None of the v0.1 node targets (compute_EW, rb_setline, rb_iter_contfit, zfind, IFU
   utilities) are affected.
5. **SciPy 1.15 removed `scipy.signal.cwt` and `ricker`**, which `rbcodes/IGM/find_line_features_wavelet.py` imports at module
   level; the module fails to import with the SciPy 1.18 that a fresh environment resolves. Not Python-version specific.
   Upstream follow-up: `pywt.cwt` (which would justify a `wavelets` extra) or a vendored ricker kernel. Not a v0.1 node target.
6. **Python 3.12 `SyntaxWarning: invalid escape sequence '\p'`** in `IGM/compute_EW.py:367,369` (`\pm` inside a non-raw
   f-string). Harmless today, becomes a `SyntaxError` in a future Python. Upstream follow-up: raw strings.
7. Stale tests listed in the table above (13 + 1). Upstream follow-up; they are not needed by Astro Canvas, which will
   keep its own numerical fixtures generated from rbcodes (design §13).
8. `setup.cfg` still pulls `pytest`, `pytest-cov`, and `PyQt5` as hard runtime dependencies. Slimming server installs
   (`rbcodes[gui]` extra) is already on `handoffs/BACKLOG.md`.

## The patch (`docs/dev/rbcodes-upstream.patch`)

13 files, applies cleanly with `git apply -p1` on commit `4499012`:

- `setup.cfg`: `python_requires = >=3.10,<3.14`; new extra `lls = rbvfit, h5py`.
- 12 modules: guard the module-level `matplotlib.use('Qt5Agg')` / `mpl.use('Qt5Agg')` behind `MPLBACKEND`.

It has **not** been pushed anywhere. Next step for the maintainer: push it to a fork (or open a PR on
`rongmon/rbcodes`) and point `packs/rbcodes/pyproject.toml` at that commit without the `python_full_version < '3.11'`
marker that currently keeps `uv lock` satisfiable.

## Consequences for Astro Canvas

- `packs/rbcodes` must import rbcodes **lazily inside node functions** with `MPLBACKEND` already set (CONVENTIONS §8),
  even after the patch, because unpatched installs exist in the wild.
- The backend environment runs NumPy 2; nodes wrapping `halo/` or `lensing/` (not in v0.1) need `np.trapezoid` shims or
  an upstream fix first.
- Phase 05 numerical fixtures should be produced with the versions in the table above and stored with the rbcodes commit.
