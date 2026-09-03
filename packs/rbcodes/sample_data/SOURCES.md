# Sample data

Copied into `<workspace>/samples/rbcodes/` on first run so every install has real spectra to try.

| File | Origin | Notes |
|---|---|---|
| `sdss1.fits`, `sdss2.fits`, `spec-0398-51789-0282.fits` | [rbcodes](https://github.com/rongmon/rbcodes) `example-data/` (SDSS DR spectra, `COADD` binary table with `loglam`, `flux`, `ivar`, `model`) | Public SDSS data redistributed by rbcodes (MIT, see `LICENSE`). |
| `test.fits` | rbcodes `example-data/` | Multi-extension 1-d spectrum (`FLUX`, `ERROR`, `WAVELENGTH`, `CONTINUUM`), the `rb_write_fits` layout. |
| `galaxy1.fits` | rbcodes `example-data/` | Binary table with `WAVELENGTH`, `FLUX`, `ERROR`, `CONTINUUM` columns. |
| `spectrum_OII_carc_Middle.dat` | rbcodes `example-data/` | ASCII spectrum with a `wave flux flux_err continuum` header. |
| `synthetic_image.fits` | generated for Astro Canvas | 96×80 float32 image, two Gaussian sources, rotated `RA---TAN`/`DEC--TAN` WCS (`CD` matrix). |
| `synthetic_kcwi_icubes.fits`, `synthetic_kcwi_vcubes.fits` | generated for Astro Canvas | 240×30×24 KCWI-style cube (`AWAV` axis, `CD3_3 = 0.5 Å`) with an emission line, plus the variance sidecar following the KCWI `_vcubes` naming. |

The rbcodes example cubes (`long_radd.fits`, 65 MB; `eiger-mock-data/`, 111 MB) exceed the 50 MB
budget for bundled samples, so the cube demo uses the synthetic file above. rbcodes is MIT licensed
(`LICENSE` in this folder is its license text); the synthetic files are MIT like this repository.
