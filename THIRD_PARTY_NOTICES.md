# Third-party notices

Meridian Ebooks itself is MIT-licensed (see [LICENSE](LICENSE)). It includes, or installs, the components below under their own licences.

## Files shipped in this repository

### Fonts - `app/static/fonts/`
Latin subsets (WOFF2) of open-source fonts, all under the **SIL Open Font License 1.1** (OFL). Each family's licence and copyright
notice is in `app/static/fonts/licenses/`; the files come from the [Fontsource](https://fontsource.org) packages.

| Family | Copyright holder |
|---|---|
| Inter | The Inter Project Authors |
| DM Sans | The DM Sans Project Authors |
| Source Sans 3 | Adobe (Reserved Font Name "Source") |
| IBM Plex Sans | IBM Corp. |
| Nunito | The Nunito Project Authors |
| Poppins | The Poppins Project Authors |
| Space Grotesk | The Space Grotesk Project Authors |
| Lora | The Lora Project Authors (Reserved Font Name "Lora") |
| Merriweather | The Merriweather Project Authors (Reserved Font Name "Merriweather") |
| Atkinson Hyperlegible | Braille Institute of America, Inc. |
| JetBrains Mono | The JetBrains Mono Project Authors |

The fonts are not sold on their own, and the licence text travels with them. The files are format-converted and Latin-only subsets;
the three families that declare a Reserved Font Name (Source Sans 3, Lora, Merriweather) are used under their original names, as is
common for web-font distributions - see the note in the README if you redistribute them separately.

### Swagger UI - `app/static/vendor/`
[Swagger UI](https://github.com/swagger-api/swagger-ui) 5.17.14 (`swagger-ui-bundle.js`, `swagger-ui.css`), **Apache License 2.0**,
Copyright 2020-2021 SmartBear Software Inc. Licence: `LICENSE-swagger-ui.txt`; notice: `NOTICE-swagger-ui.txt`.
The bundle also contains permissively licensed libraries (React, Redux, Immutable and others); upstream points to a
`swagger-ui-bundle.js.LICENSE.txt` for them that it does not publish, so refer to the Swagger UI project for that list.

### Icons - `app/static/js/api.js`
The outline icon paths follow the style of, and in places match, [Feather](https://feathericons.com) and [Lucide](https://lucide.dev) icons.
Their licences are reproduced here:

> **Feather** - MIT License. Copyright (c) 2013-2017 Cole Bemis.
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
> (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
> publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
> subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
> BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
> ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
>
> **Lucide** - ISC License. Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT).
> All other copyright (c) for Lucide are held by Lucide Contributors 2022. Permission to use, copy, modify, and/or distribute this
> software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice
> appear in all copies. THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE
> INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
> INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
> CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

### Screenshots - `docs/screenshots/`
Created by this project from demo data. The covers are generated gradients, not real book covers, and the book text is placeholder text.
Titles and author names shown are only labels.

## Installed with `pip` (not stored in this repository)

| Package | Licence | Where |
|---|---|---|
| FastAPI, Starlette, Pydantic, annotated-types, anyio, h11 | MIT / BSD-3-Clause | runtime |
| Uvicorn, Click, idna | BSD-3-Clause | runtime |
| python-multipart | Apache-2.0 | runtime |
| lxml (bundles libxml2, libxslt) | BSD-3-Clause (libraries MIT) | runtime |
| Pillow | MIT-CMU (bundles libjpeg-turbo, zlib, FreeType and others under their own permissive licences) | runtime |
| typing-extensions | PSF-2.0 | runtime |
| pypdf | BSD-3-Clause | runtime (reads and writes PDF metadata) |
| pypdfium2 (bundles Google's PDFium and its libraries) | BSD-3-Clause or Apache-2.0; PDFium BSD-3-Clause / Apache-2.0 plus the licences of its own dependencies, shipped inside the wheel | runtime (renders the first page of a PDF as its cover) |
| pytest, pytest-cov | MIT | tests only |
| coverage | Apache-2.0 | tests only |
| httpx / httpcore, certifi | BSD-3-Clause, MPL-2.0 | tests only |
| Playwright | Apache-2.0 | screenshot script only |

The Docker image also contains the Debian-based `python:3.12-slim` image (Python under the PSF licence plus Debian packages under their
own licences, including GPL/LGPL components) and `libjpeg62-turbo` (IJG / BSD).

### Copyleft
No runtime dependency is copyleft. PDF support deliberately uses pypdf and pypdfium2 instead of PyMuPDF, which is AGPL-3.0 and would have
put the whole application under the AGPL's source-offer terms. `certifi` (MPL-2.0, weak copyleft, file-level) is only used by the test
suite and is not part of the Docker image.
