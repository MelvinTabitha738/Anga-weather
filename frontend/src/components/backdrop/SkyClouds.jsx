/**
 * Moving cloud layers for the hero sky.
 *
 * Five soft, blurred ovals drifting horizontally at three speeds, staggered by
 * negative animation delays so the sky is already mid-motion on first paint
 * rather than starting empty and filling up.
 *
 * Pure CSS, looping infinitely — see styles/clouds.css. Nothing here is
 * measured or data-driven; it is atmosphere, so it stays decorative and
 * aria-hidden.
 *
 * Heights are ~50% taller than the supplied values because the shapes carry a
 * 30px blur: on a 48px-tall oval that removes most of the peak opacity before
 * it reaches the screen.
 */
const clouds = [
  { top: '8%', width: '42vw', height: '15vh', delay: '-12s', speed: 'cloud-slow', opacity: 0.22 },
  { top: '18%', width: '28vw', height: '11vh', delay: '-32s', speed: 'cloud-medium', opacity: 0.16 },
  { top: '34%', width: '56vw', height: '18vh', delay: '-5s', speed: 'cloud-slow', opacity: 0.18 },
  { top: '6%', width: '20vw', height: '10vh', delay: '-22s', speed: 'cloud-fast', opacity: 0.12 },
  { top: '52%', width: '36vw', height: '14vh', delay: '-44s', speed: 'cloud-medium', opacity: 0.14 },
]

export default function SkyClouds() {
  return (
    <div className="cloud-layer" aria-hidden="true" data-testid="sky-clouds">
      {clouds.map((cloud, index) => (
        <div
          key={index}
          className={`cloud-shape ${cloud.speed}`}
          style={{
            top: cloud.top,
            left: '-60vw',
            width: cloud.width,
            height: cloud.height,
            animationDelay: cloud.delay,
            opacity: cloud.opacity,
          }}
        />
      ))}
    </div>
  )
}
