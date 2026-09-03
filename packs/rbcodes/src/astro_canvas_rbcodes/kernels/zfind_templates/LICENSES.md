# zfind template data

Bundled so `rbcodes.zfind.template_search` and `rbcodes.zfind.pca_search` work without a
network or an rbcodes install. Copied from rbcodes 2.4.0 (`src/rbcodes/GUIs/zfind/templates/`,
commit `4499012`), which fetched them with `download_marz_templates.py` and `download_desi_pca.py`.

| Folder | Files | Origin | Licence |
|---|---|---|---|
| `marz/` | `EarlyType`, `Intermediate`, `LateTypeEmission`, `Composite`, `QSO` (`.fits`, `WAVE` + `FLUX` HDUs) | [MARZ](https://github.com/Samreay/Marz) `js/templates.js` (Hinton et al. 2016) | MIT |
| `pca/` | `rrtemplate-QSO-LOZ-v1.1.fits`, `rrtemplate-QSO-HIZ-v1.1.fits`, `rrtemplate-GALAXY-None-v2.6.fits` | [desihub/redrock-templates](https://github.com/desihub/redrock-templates) | BSD 3-Clause |

`rrtemplate-GALAXY-None-v2.6.fits` is reduced to every 9th pixel of the `BASIS_VECTORS` HDU
(97 720 -> 10 858 pixels, `CDELT1` 0.1 -> 0.9 Angstrom) and drops the `ARCHETYPE_COEFF` HDU. This is
exactly the stride rbcodes' `_load_pca` applies at load time (`n_pix // 10_000`), so the kernels and
rbcodes see identical eigenvectors while the file shrinks from 9.4 MB to 0.9 MB.
