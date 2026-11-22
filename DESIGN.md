---
name: EventRank
description: Vietnamese news events, grouped across papers and ranked by how fast the press covers them.
colors:
  surface: "#e4e8f0"
  shadow-light: "#ffffff"
  shadow-dark: "#bcc4d2"
  ink: "#1f2736"
  ink-soft: "#3c4657"
  muted: "#4f5a6e"
  muted-soft: "#586478"
  line: "#cdd4e0"
  outline: "#78839a"
  indigo: "#3047c0"
  indigo-deep: "#263aa3"
  indigo-tint: "#d7ddf3"
  danger: "#a32a20"
  danger-tint: "#f2dcd8"
  ok: "#2a6b45"
  ok-tint: "#d6e8dc"
  warn: "#75590f"
  warn-tint: "#efe5c8"
typography:
  display:
    fontFamily: "Nunito, Segoe UI, system-ui, sans-serif"
    fontSize: "46px"
    fontWeight: 800
    lineHeight: 1.12
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Nunito, Segoe UI, system-ui, sans-serif"
    fontSize: "31px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.014em"
  title:
    fontFamily: "Nunito, Segoe UI, system-ui, sans-serif"
    fontSize: "18.5px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Nunito, Segoe UI, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 500
    lineHeight: 1.55
  label:
    fontFamily: "Nunito, Segoe UI, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 700
    lineHeight: 1.4
rounded:
  sm: "10px"
  md: "14px"
  lg: "22px"
spacing:
  sm: "10px"
  md: "18px"
  lg: "26px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.shadow-light}"
    rounded: "{rounded.md}"
    padding: "11px 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.indigo-deep}"
  button-soft:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "44px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 13px"
    height: "44px"
  tile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "22px"
---

# Design System: EventRank

## Overview

**Creative North Star: "One Soft Surface"**

Everything is pressed out of, or into, a single cool surface. A raised shape can be read or pressed; a sunken shape holds a value or takes input. The hottest event rises furthest.

Neumorphism usually fails on legibility, so this system keeps its softness in the shapes and keeps its signals firm: dark ink text, one solid indigo for the main action, and a thin outline on secondary controls and fields.

Motion is physical and brief. Tiles lift in on load, heat grooves fill, the replay hour ticks, and controls sink when pressed. All of it stops once the page settles.

**Key Characteristics:**
- One surface colour for page, tiles and controls
- Paired light and dark soft shadows for raised and sunken states
- Solid indigo reserved for the main action, links and focus
- Inset grooves for hotness and per-paper article counts
- Short, physical motion that ends after load

## Colors

A single cool grey-blue carries the page; colour appears only where it means something.

### Primary
- **Signal Indigo**: main actions, links, focus rings and heat fills.
- **Deep Indigo**: hover state of Signal Indigo.

### Neutral
- **Soft Surface**: the page, every tile and every soft control.
- **Light Shadow** and **Dark Shadow**: the paired shadows that make shapes rise or sink.
- **Ink** and **Soft Ink**: headings and body text.
- **Muted Ink**: metadata; never lighter than the muted-soft token.
- **Outline**: the visible edge of secondary controls and fields, at 3:1 against the surface.

### Tertiary
Six muted paper colours live with the source table in the web app and identify each newspaper.

### Named Rules
**The Firm Signal Rule.** Softness never carries meaning alone. Text keeps 4.5:1, and any control a person must find has a solid fill or an outline.

**The One Indigo Rule.** Only one action colour exists. A screen has one primary button in a given area.

## Typography

**Display Font:** Nunito (with Segoe UI, system-ui)
**Body Font:** Nunito (with Segoe UI, system-ui)

**Character:** A rounded sans with full Vietnamese diacritics; its soft terminals match the raised shapes while heavy weights keep hierarchy clear.

### Hierarchy
- **Display**: the home question; 30px on phones.
- **Headline**: event titles and the rank 1 event name.
- **Title**: event names in lists and article titles, capped near 62ch.
- **Body**: interface copy and notes.
- **Label**: metadata, tags and filter labels.

## Layout

Content sits in a 1200px container with 24px gutters (16px on phones), with a main column and a roughly 300px side column that stacks below 900px. Ranked events are separated tiles with an 18px gap so shadows have room. Rank 1 is always the largest tile and opens by default.

## Elevation & Depth

Depth is the whole system. Three raised levels mark importance and one inset level marks wells, fields and active states. Phones use smaller shadow offsets. Exact shadow values live in the design sidecar.

### Named Rules
**The Press Rule.** Raised means pressable or readable; pressing or selecting moves a shape to the inset level, never to a new colour alone.

## Shapes

Large soft radii: 22px tiles, 14px controls, 10px fields and segments. Circles hold ranks and paper initials.

## Components

### Buttons
- **Shape:** soft corners (14px), 44px tall.
- **Primary:** solid Signal Indigo with white text, raised.
- **Hover / Focus:** lifts 1px and darkens; 2px indigo focus ring.
- **Soft:** surface colour with a thin outline; sinks when pressed.

### Chips
- **Style:** raised surface pills; lift on hover and sink when pressed.

### Cards / Containers
- **Corner Style:** 22px.
- **Background:** Soft Surface.
- **Shadow Strategy:** raised levels from Elevation & Depth; no borders.
- **Internal Padding:** 22px.

### Inputs / Fields
- **Style:** sunken with a thin outline.
- **Focus:** 2px indigo outline.
- **Error / Disabled:** danger text below the field; 55% opacity when disabled.

### Navigation
A raised sticky bar with plain text links. Hover raises a link and the active link sinks and turns indigo. On phones, links collapse behind a menu button with search and account icons visible.

### Event Tile
Rank in a sunken circle, name, metadata, and a heat groove scaled to rank 1. One tile opens at a time to show actions.

### Paper Groove
On an event page, a sunken groove split into one coloured segment per paper, sized by the real article count.

## Do's and Don'ts

### Do:
- **Do** keep page, tiles and soft controls on the same surface colour.
- **Do** give every secondary control and field a visible outline.
- **Do** keep the replay and unevaluated-score labels next to the data they qualify.
- **Do** disable all motion under `prefers-reduced-motion`.

### Don't:
- **Don't** set body or metadata text lighter than the muted-soft token.
- **Don't** nest raised tiles inside raised tiles.
- **Don't** loop animations on content after the page settles.
- **Don't** use a paper colour for decoration.
