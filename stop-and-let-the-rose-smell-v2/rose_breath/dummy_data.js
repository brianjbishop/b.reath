// dummy_data.js — synthetic breath patterns for testing rose_breath without
// phones/bridge/OSC. Loaded as a plain <script> (not fetch()) so it works
// under file:// in every browser, including Chrome.
//
// Each entry describes one performer's breathing pattern. index.html turns
// these parameters into a live, continuously-varying 0–1 signal each frame —
// see sampleDummyDevice() there.
//
//   uuid            — stable id, used for color assignment like a real device
//   label            — human-readable name (not currently drawn, but handy when editing)
//   period_s         — seconds per breath cycle
//   ampMin / ampMax  — breath value range this performer swings through
//   shape            — 'sine' | 'box' | 'sawtooth'
//   periodJitter     — 0–1, how much the cycle length wobbles cycle-to-cycle (sine only)
//   ampJitter        — 0–1, how much noise is added on top of the shaped curve
//   inhaleFrac       — sawtooth only: fraction of the cycle spent inhaling (rest is exhale)
//   dropoutAfter_s   — if set, this performer goes silent after this many seconds,
//                       exercising the real 5s device-timeout/fade-out path
//   seed             — decorrelates the noise used by periodJitter/ampJitter between devices

window.DUMMY_DATA = [
  {
    uuid: 'dummy-slow-deep',
    label: 'Slow & Deep',
    period_s: 10,
    ampMin: 0.10,
    ampMax: 0.95,
    shape: 'sine',
    seed: 0,
  },
  {
    uuid: 'dummy-fast-shallow',
    label: 'Fast & Shallow',
    period_s: 2.5,
    ampMin: 0.10,
    ampMax: 0.45,
    shape: 'sine',
    seed: 1,
  },
  {
    uuid: 'dummy-irregular',
    label: 'Irregular',
    period_s: 5,
    ampMin: 0.10,
    ampMax: 0.80,
    shape: 'sine',
    periodJitter: 0.45,
    ampJitter: 0.25,
    seed: 2,
  },
  {
    uuid: 'dummy-box',
    label: 'Box Breathing',
    period_s: 16,
    ampMin: 0.05,
    ampMax: 0.90,
    shape: 'box',
    seed: 3,
  },
  {
    uuid: 'dummy-asymmetric',
    label: 'Asymmetric Natural',
    period_s: 5,
    ampMin: 0.15,
    ampMax: 0.85,
    shape: 'sawtooth',
    inhaleFrac: 0.3,
    seed: 4,
  },
  {
    uuid: 'dummy-dropout',
    label: 'Drops Out',
    period_s: 6,
    ampMin: 0.10,
    ampMax: 0.80,
    shape: 'sine',
    dropoutAfter_s: 20,
    seed: 5,
  },
];
