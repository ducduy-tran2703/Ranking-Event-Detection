# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: Vietnamese news readers who want to know, within seconds and often on a phone, which real-world events the press is covering hardest right now and why. Confirmed by the project owner on 2026-11-09 as the side that wins trade-offs.

Secondary: lecturers and the student team inspecting data quality and model results on the dedicated "Dữ liệu & mô hình" pages; administrators using the separate admin area.

## Product Purpose

EventRank groups articles from Vietnamese newspapers into events, gives each event a short generated name, and ranks events by how fast the press is covering them. Success means a reader opens the home page and immediately understands what is hot, how many papers carry it, and can go deeper into one event.

This is a student capstone project (Đồ án PBL) at Vietnamese university level, not a commercial service.

## Positioning

The unit is the event, not the article: twelve papers reporting the same happening are one event. The board can be replayed hour by hour across the collected period, showing what was hot at any past hour.

## Operating Context

The dataset comes from one pipeline run over collected articles from six papers (Tuổi Trẻ, Thanh Niên, VietnamNet, Nhân Dân, VnExpress, Báo Chính phủ); the crawler does not run continuously yet, so the board is a replay, and the interface must say so. Readers can also ask questions over the corpus (Hỏi đáp, RAG) and receive answers citing articles. Registered users can save and follow events.

## Capabilities and Constraints

- React + Vite + TypeScript in `apps/web/`; the backend is FastAPI. Frontend calls go only through `apps/web/src/api/`. The API contract and existing routes do not change in this redesign.
- All UI text is Vietnamese with correct diacritics; numbers use Vietnamese format (1.234; 9,93) and tabular figures.
- Terminology: "sự kiện" (event), "độ nóng" (hotness), "chuyên mục" (category), "báo" (paper), "phát lại" (replay).
- The admin area keeps its layout in this redesign and only inherits new tokens.
- Undecided: dark theme; the mobile app is not built.

## Brand Commitments

The name EventRank stays. Existing visuals are not binding: the owner chose a full visual replacement on 2026-11-09.

## Evidence on Hand

Real data through the API: events, articles, hourly trend scores, categories, data quality and model pages. Honest labels that must survive: the board is a replay rather than real time; the hotness score is a formula that has not been evaluated; model names can be hidden for the naming test window; account features may run in mock mode. There are no testimonials, customers or usage numbers, and none may be invented.

## Product Principles

- The event comes first; articles are its evidence.
- State plainly what the data is and is not: replay, unevaluated score, hidden names.
- Answer "what is hot and why" before offering controls.
- Every number shown comes from the API; if it is missing, hide it rather than fabricate it.

## Accessibility & Inclusion

Text contrast at least 4.5:1, touch targets at least 44px, keyboard focus visible, and all motion disabled under `prefers-reduced-motion`. These are existing project commitments.
