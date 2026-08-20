import { useEffect, useRef } from 'react'

/**
 * Canvas rainfall whose density follows the reported intensity.
 *
 * Performance rules this obeys:
 * - one canvas, one rAF loop, no per-drop DOM nodes
 * - the loop stops when the tab is hidden and when reduced motion is preferred
 * - drop count is capped by the caller (RAIN_DENSITY in weatherTheme)
 * - the backing store is sized to devicePixelRatio, capped at 2, so retina
 *   phones stay sharp without quadrupling the fill cost
 */
export default function RainCanvas({ dropCount = 0, stormy = false }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || dropCount <= 0) return undefined

    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    const context = canvas.getContext('2d')
    if (!context) return undefined

    let width = 0
    let height = 0
    let drops = []
    let frame = null

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = Math.floor(width * ratio)
      canvas.height = Math.floor(height * ratio)
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
    }

    const seed = () => {
      drops = Array.from({ length: dropCount }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        // Longer, faster streaks read as heavier rain.
        length: 8 + Math.random() * (stormy ? 22 : 14),
        speed: 260 + Math.random() * (stormy ? 420 : 240),
        drift: stormy ? 70 + Math.random() * 60 : 20 + Math.random() * 30,
        alpha: 0.18 + Math.random() * 0.35,
      }))
    }

    resize()
    seed()

    if (reduceMotion) {
      // Draw a single static frame so the weather is still legible without
      // any motion at all.
      context.clearRect(0, 0, width, height)
      context.lineWidth = 1.1
      context.lineCap = 'round'
      drops.forEach((drop) => {
        context.strokeStyle = `rgba(214, 232, 255, ${drop.alpha})`
        context.beginPath()
        context.moveTo(drop.x, drop.y)
        context.lineTo(drop.x - drop.drift * 0.05, drop.y + drop.length)
        context.stroke()
      })
      return () => {}
    }

    let lastTime = performance.now()

    const draw = (now) => {
      // Delta-time integration keeps the fall speed identical on 60Hz and
      // 120Hz displays. Clamped so a backgrounded tab does not teleport rain.
      const delta = Math.min((now - lastTime) / 1000, 0.05)
      lastTime = now

      context.clearRect(0, 0, width, height)
      context.lineWidth = 1.1
      context.lineCap = 'round'

      for (const drop of drops) {
        drop.y += drop.speed * delta
        drop.x += drop.drift * delta

        if (drop.y - drop.length > height) {
          drop.y = -drop.length
          drop.x = Math.random() * width
        }
        if (drop.x > width + 20) drop.x = -20

        context.strokeStyle = `rgba(214, 232, 255, ${drop.alpha})`
        context.beginPath()
        context.moveTo(drop.x, drop.y)
        context.lineTo(drop.x - drop.drift * 0.05, drop.y + drop.length)
        context.stroke()
      }

      frame = requestAnimationFrame(draw)
    }

    frame = requestAnimationFrame(draw)

    const onVisibility = () => {
      if (document.hidden) {
        if (frame) cancelAnimationFrame(frame)
        frame = null
      } else if (!frame) {
        lastTime = performance.now()
        frame = requestAnimationFrame(draw)
      }
    }

    const onResize = () => {
      resize()
      seed()
    }

    window.addEventListener('resize', onResize)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [dropCount, stormy])

  if (dropCount <= 0) return null

  return <canvas ref={canvasRef} className="backdrop__rain" aria-hidden="true" />
}
