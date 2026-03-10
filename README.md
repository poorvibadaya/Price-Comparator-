# Fast E-commerce Product Compare

A modern product comparison website for quick delivery platforms.

## Quick Start

**Terminal 1 - Backend:**
```bash
cd backend
pip install -r requirements.txt
python app.py
```

**Terminal 2 - Frontend:**
```bash
npm install
npm run dev
```

Open: `http://localhost:5173/`

## Features

- ⚡ Compare products from 8+ quick delivery platforms
- 📍 Location-based pricing and availability  
- ⏱️ Delivery time comparison (10-30 min focus)
- 💰 Price comparison with best deal highlighting
- 🎯 Advanced filtering by platform, price, delivery time, ratings

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS
- **Backend**: Python Flask + Web Scraping
- **UI**: shadcn/ui components + Lucide icons

## Project Structure & Context

This repository contains three independent parts of the application. **You need to run the backend and at least one frontend (web or mobile) for the app to work.**

- **`/` (Root Folder) - React Web Frontend**:
  - The web application built with React 18, Vite, and Tailwind CSS.
  - Run with `npm install` and `npm run dev`.
  - Communicates with the Python API on port 8080.
- **`/backend/` - Python Flask API & Scrapers**:
  - The core engine that searches for products across various platforms using Playwright.
  - Run with `pip install -r requirements.txt`, `playwright install chromium`, and `python app.py`.
  - Exposes `http://localhost:8080/api/search`.
  - See `backend/README.md` for more details.
- **`/groease-mobile/` - React Native Expo App**:
  - The mobile version of the web app.
  - Run with `npm install --legacy-peer-deps` and `npm start`.
  - See `groease-mobile/SETUP.md` for more details.

## Supported Platforms & Architecture

- **Location Finding**: Proxies Geoapify to fetch coordinates for all platforms.
- **Scraping**: Passes the location and query to Playwright, which opens isolated headless browsers for each platform concurrently.
- **Processing**: Sorts, name-matches, and combines JSON outputs natively across platforms.
- **Comparison**: Displays merged results on the web or mobile app, highlighting the quickest delivery or cheapest price.
- **Future Improvements**: Make scraping fundamentally async, stream results back to the client as they arrive from each platform, and merge quantities directly in search results.

