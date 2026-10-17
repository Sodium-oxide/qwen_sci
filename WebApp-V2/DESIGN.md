# QwenSci visual system

## Direction

Code-led implementation of the user-approved research-report direction. A trace from question to evidence, model, review and artifact connects marketing to the actual research workflow. Marketing uses editorial composition; workspace screens prioritize stable controls and reading.

## Tokens

Background #0A0A0B; surface #101012; raised #151518; ink #F0EEE8; muted #A7A6A2; primary #9BA7FF; primary-hover #AAB4FF; action #D29C52; action-hover #E0AE66; success #5FD6A0; danger #F26B7A; paper #F3F0E9.

Self-host IBM Plex Sans and Serif for Latin; system Chinese sans and serif fallbacks. Display 30–64px; interface 14–16px; reading 16–18px. Spacing 4, 8, 12, 16, 24, 32, 48, 72, 96px. Interface radii 6–14px. Decorative separators never substitute for accessible control boundaries.

## Composition and Behavior

Public pages use an approximately 42% editorial axis and real representative artifacts. Workspace has a 224px navigation rail, 56px header, flexible main and optional inspector. Narrow layouts collapse navigation and inspectors into accessible drawers and reading views. One primary action per local task.

Motion 150–250ms, reduced-motion supported. Progress and capability claims come from the server. Errors name recovery and expose safe request IDs. Reviews distinguish accepting output, preserving source and regenerating selected content.

## Homepage Brand Visual

The homepage hero forms the user's Qwen logo entirely from blue-white particles. The transparent SVG traced from the supplied image is an offscreen sampling mask, preserving the original three-arm silhouette and proportions. Individual particles flow along each arm while a slow wave of light passes through them. The visible mark has no solid fill or background plate. A dark spherical core and tilted blue-white particle rings follow the supplied motion reference. This treatment belongs to the hero illustration; workspace controls keep the existing restrained styling.

Particles flow continuously at a capped 30 fps with a visible pause/play control. Stop the animation when the illustration is offscreen or the browser tab is hidden. Reduced-motion preferences render the complete particle logo and orbit as a static composition. Cache the sphere, tracks, logo masks and glow sprites per scene; cap the canvas pixel ratio at 2 and reduce the particle count on narrow screens.
