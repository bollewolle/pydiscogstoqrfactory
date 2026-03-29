# Discogs QR Code Generator

A web application that connects to the Discogs API to retrieve your record collection and generates QR code stickers for your physical releases — either as a printable PDF with sticker sheet layouts, or as a CSV file compatible with [QR Factory 3](https://www.tunabellysoftware.com/qrfactory/).

## Features

- **Discogs OAuth Authentication** — Secure web-based OAuth 1.0a login
- **Auto-authentication** — Automatically uses stored credentials from `.env` or database
- **Browse by Folders** — Navigate your Discogs collection by folder
- **Browse by Format** — Browse by format (Vinyl, CD, etc.), then by size (12", 7", etc.), with description filters (LP, Album, Single, etc.)
- **Latest Additions** — Find releases added since a specific date
- **Sorting** — Sort by Artist (A-Z/Z-A), Year (Newest/Oldest), or Date Added
- **Flexible Selection** — Select individual releases, all releases, or filter by artist starting letter
- **QR Code PDF Generation** — Generate printable PDF sticker sheets with QR codes featuring the Discogs logo overlay
- **Configurable Sticker Layouts** — Define page size, sticker dimensions, margins, and spacing; includes standard layouts (Default A4, Avery L7120-25, Avery L7121-25) with visual preview
- **Sticker Slot Activation** — Deactivate individual sticker slots to reuse partially printed pages
- **QR Factory 3 CSV Export** — Generate CSV files in the exact format expected by QR Factory 3, with preview and edit before downloading
- **Customizable Text below QR Code** — Configure what text appears below the QR code via the Settings page, using any combination of artist, title, year, folder, format, size, and description
- **Processing Tracker** — Keeps track of releases already processed to avoid duplicates
- **Breadcrumb Navigation** — Easy navigation throughout the app
- **Collection Caching** — API results are cached for 5 minutes to speed up browsing

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [mise](https://mise.jdx.dev/) (optional, for environment management)
- A [Discogs developer application](https://www.discogs.com/settings/developers) (for API credentials)
- [QR Factory 3](https://www.tunabellysoftware.com/qrfactory/) (optional — macOS app, only needed for the CSV export workflow)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/bollewolle/pydiscogsqrcodegenerator.git
cd pydiscogsqrcodegenerator
```

### 2. Set up environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your Discogs API credentials:

```env
DISCOGS_CONSUMER_KEY=your_consumer_key
DISCOGS_CONSUMER_SECRET=your_consumer_secret
```

Optionally, if you already have OAuth tokens:

```env
DISCOGS_OAUTH_TOKEN=your_oauth_token
DISCOGS_OAUTH_TOKEN_SECRET=your_oauth_token_secret
```

### 3. Install dependencies

```bash
uv sync
```

### 4. Run the application

```bash
uv run flask run
```

The app will be available at `http://localhost:5000`.

## Usage

1. **Login** — Click "Login with Discogs" to authenticate via OAuth, or the app will auto-authenticate if credentials are configured in `.env`.

2. **Browse** — Choose between "Browse by Folders" to navigate by folder, "Browse by Format" to navigate by format and size, or "Latest Additions" to find recently added releases.

3. **Select** — Use checkboxes to select individual releases, or use "Select All" / letter filters. Releases previously processed are marked with a "Processed" badge.

4. **Settings (optional)** — Click "Settings" in the navbar to customize the text template below the QR code, manage sticker layouts, and select the active layout.

5. **Export as PDF** — Click "Preview QR Code PDF" to see a page-by-page sticker preview matching your selected layout. Deactivate individual slots to skip already-used sticker positions. Click "Download QR Code PDF" to generate the printable PDF.

6. **Export as QR Factory 3 CSV** — Click "Preview QR Factory 3 CSV" to see the generated CSV data. Optionally click "Edit Before Download" to modify individual fields. Click "Download QR Factory 3 CSV" to get the file, then import it into QR Factory 3.

## Docker

A pre-built Docker image is published to GitHub Container Registry on every push to `main`. You can run the app standalone or add it to an existing Docker Compose stack.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (included with Docker Desktop)
- A [Discogs developer application](https://www.discogs.com/settings/developers) (for API credentials)

### Standalone setup

#### 1. Clone the repository

```bash
git clone https://github.com/bollewolle/pydiscogsqrcodegenerator.git
cd pydiscogsqrcodegenerator
```

#### 2. Set up environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your Discogs API credentials:

```env
DISCOGS_CONSUMER_KEY=your_consumer_key
DISCOGS_CONSUMER_SECRET=your_consumer_secret
```

#### 3. Start the application

```bash
docker compose up -d
```

The app will be available at `http://localhost:8721`.

### Adding to an existing Docker Compose stack

To add this app to an existing `docker-compose.yml`, add the following service definition:

```yaml
services:
  # ... your other services ...

  discogs-qr:
    image: ghcr.io/bollewolle/pydiscogsqrcodegenerator:latest
    ports:
      - "8721:5001"
    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - FRONTEND_URL=http://your-server-ip-or-domain:8721
      - DISCOGS_CONSUMER_KEY=your_consumer_key
      - DISCOGS_CONSUMER_SECRET=your_consumer_secret
      # Optional: add these if you have OAuth tokens
      # - DISCOGS_OAUTH_TOKEN=your_oauth_token
      # - DISCOGS_OAUTH_TOKEN_SECRET=your_oauth_token_secret
      - USERAGENT=pydiscogsqrcodegenerator/1.0
    volumes:
      - discogs-qr-data:/app/instance
    restart: unless-stopped

volumes:
  # ... your other volumes ...
  discogs-qr-data:
```

**Important:** `FRONTEND_URL` must match the URL you use to access the app in your browser (e.g. `http://192.168.1.50:8721` or `https://discogs-qr.yourdomain.com`). This is used to build the Discogs OAuth callback URL. If hosting remotely, `localhost` will not work.

Alternatively, instead of inline environment variables, you can use an `env_file` pointing to a `.env` file (see `.env.example` in this repository for the full list of variables).

### Updating to the latest version

Pull the latest image and recreate the container:

```bash
docker compose pull
docker compose up -d
```

### Persistent data

The SQLite database and session files are stored in a Docker volume. Your data persists across container restarts and updates. To completely reset the data:

```bash
docker compose down -v
```

### Building locally (optional)

If you prefer to build the image yourself instead of using the pre-built one, replace `image:` with `build:` in your `docker-compose.yml`:

```yaml
services:
  discogs-qr:
    build: .
    # ... rest of the configuration stays the same
```

Then build and start:

```bash
docker compose up -d --build
```

## Development

### Running tests

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov=pydiscogsqrcodegenerator
```

### Project structure

```
src/pydiscogsqrcodegenerator/
├── __init__.py            # App factory
├── config.py              # Configuration classes
├── extensions.py          # Flask extensions
├── models.py              # Database models (UserSettings, StickerLayout, ProcessedRelease)
├── discogs_service.py     # Discogs API wrapper
├── csv_service.py         # QR Factory 3 CSV generation service
├── pdf_service.py         # QR code PDF sticker sheet generation
├── blueprints/
│   ├── auth.py            # OAuth authentication routes
│   ├── collection.py      # Collection browsing routes
│   ├── export.py          # CSV and PDF export routes
│   └── settings.py        # User settings and sticker layout routes
├── templates/             # Jinja2 HTML templates
└── static/                # CSS, JavaScript, and Discogs logo
```

### QR Factory 3 CSV format

The CSV template is defined in `templates/qrfactory_discogs_collection_template.csv`. Each row represents a QR code with:

- **Type**: URL
- **Content**: Link to the Discogs release page
- **BottomText**: Customizable via Settings (default: `Artist – Title [Year]` / `Folder`). Available placeholders: `{artist}`, `{title}`, `{year}`, `{discogs_folder}`, `{format_name}`, `{format_size}`, `{format_descriptions}`. This same template is also used for the text below the QR code in the PDF export.
- **FileName**: The Discogs release ID
- **Icon**: Discogs record icon overlay

Size inference: when a release has no explicit size but is described as "LP", the size is inferred as 12".

## License

MIT
