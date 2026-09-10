package com.solomonprime.tricorder

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.view.Surface
import androidx.car.app.AppManager
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.SurfaceCallback
import androidx.car.app.SurfaceContainer
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.CarColor
import androidx.car.app.model.Template
import androidx.car.app.navigation.NavigationManager
import androidx.car.app.navigation.model.NavigationTemplate
import kotlinx.coroutines.*
import kotlin.math.roundToInt
import kotlin.random.Random

/**
 * 80s Nintendo-style pixel art map overlay for Android Auto.
 *
 * Draws a retro scrolling road with pixel-art car, trees, speed readout,
 * and "TRICORDER PRIME" title — all rendered on the Car App surface canvas.
 */
class TricorderCarMapScreen(carContext: CarContext) : Screen(carContext) {

    // ── NES-style 4-bit palette (16 colors) ───────────────────────────
    private val nesPalette = intArrayOf(
        0xFF000000.toInt(), // 0  black
        0xFF1D2B53.toInt(), // 1  dark blue
        0xFF7E2553.toInt(), // 2  dark magenta
        0xFF008751.toInt(), // 3  dark green
        0xFFAB5236.toInt(), // 4  brown
        0xFF5F574F.toInt(), // 5  dark gray
        0xFFC2C3C7.toInt(), // 6  light gray
        0xFFFFF1E8.toInt(), // 7  white
        0xFFFF004D.toInt(), // 8  red
        0xFFFFA300.toInt(), // 9  orange
        0xFFFFEC27.toInt(), // 10 yellow
        0xFF00E436.toInt(), // 11 green
        0xFF29ADFF.toInt(), // 12 cyan / sky blue
        0xFF83769C.toInt(), // 13 lavender
        0xFFFF77A8.toInt(), // 14 pink
        0xFFFFCCAA.toInt(), // 15 peach
    )

    private val paint = Paint().apply { isAntiAlias = false }
    private var surface: Surface? = null
    private var surfaceWidth = 0
    private var surfaceHeight = 0
    private var animJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    // Animation state
    private var roadOffset = 0f
    private val trees = mutableListOf<TreeSprite>()
    private val rng = Random(System.currentTimeMillis())

    // ── Pixel font: each digit is a 5x5 bitmap (row-major, 1=on) ─────
    private val pixelDigits: Map<Char, List<Int>> = mapOf(
        '0' to listOf(0,1,1,1,0, 1,0,0,0,1, 1,0,0,0,1, 1,0,0,0,1, 0,1,1,1,0),
        '1' to listOf(0,0,1,0,0, 0,1,1,0,0, 0,0,1,0,0, 0,0,1,0,0, 0,1,1,1,0),
        '2' to listOf(0,1,1,1,0, 1,0,0,0,1, 0,0,1,1,0, 0,1,0,0,0, 1,1,1,1,1),
        '3' to listOf(1,1,1,1,0, 0,0,0,0,1, 0,1,1,1,0, 0,0,0,0,1, 1,1,1,1,0),
        '4' to listOf(1,0,0,1,0, 1,0,0,1,0, 1,1,1,1,1, 0,0,0,1,0, 0,0,0,1,0),
        '5' to listOf(1,1,1,1,1, 1,0,0,0,0, 1,1,1,1,0, 0,0,0,0,1, 1,1,1,1,0),
        '6' to listOf(0,1,1,1,0, 1,0,0,0,0, 1,1,1,1,0, 1,0,0,0,1, 0,1,1,1,0),
        '7' to listOf(1,1,1,1,1, 0,0,0,0,1, 0,0,0,1,0, 0,0,1,0,0, 0,0,1,0,0),
        '8' to listOf(0,1,1,1,0, 1,0,0,0,1, 0,1,1,1,0, 1,0,0,0,1, 0,1,1,1,0),
        '9' to listOf(0,1,1,1,0, 1,0,0,0,1, 0,1,1,1,1, 0,0,0,0,1, 0,1,1,1,0),
    )

    // Pixel font for TRICORDER PRIME title (simplified block letters)
    private val titleText = "TRICORDER PRIME"

    // Simple pixel letter bitmaps (5 wide x 5 tall) for the title
    private val pixelLetters: Map<Char, List<Int>> = mapOf(
        'T' to listOf(1,1,1,1,1, 0,0,1,0,0, 0,0,1,0,0, 0,0,1,0,0, 0,0,1,0,0),
        'R' to listOf(1,1,1,1,0, 1,0,0,0,1, 1,1,1,1,0, 1,0,0,1,0, 1,0,0,0,1),
        'I' to listOf(0,1,1,1,0, 0,0,1,0,0, 0,0,1,0,0, 0,0,1,0,0, 0,1,1,1,0),
        'C' to listOf(0,1,1,1,1, 1,0,0,0,0, 1,0,0,0,0, 1,0,0,0,0, 0,1,1,1,1),
        'O' to listOf(0,1,1,1,0, 1,0,0,0,1, 1,0,0,0,1, 1,0,0,0,1, 0,1,1,1,0),
        'D' to listOf(1,1,1,1,0, 1,0,0,0,1, 1,0,0,0,1, 1,0,0,0,1, 1,1,1,1,0),
        'E' to listOf(1,1,1,1,1, 1,0,0,0,0, 1,1,1,0,0, 1,0,0,0,0, 1,1,1,1,1),
        'P' to listOf(1,1,1,1,0, 1,0,0,0,1, 1,1,1,1,0, 1,0,0,0,0, 1,0,0,0,0),
        'M' to listOf(1,0,0,0,1, 1,1,0,1,1, 1,0,1,0,1, 1,0,0,0,1, 1,0,0,0,1),
        ' ' to listOf(0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0),
    )

    private data class TreeSprite(var x: Float, var y: Float, val side: Int /* -1=left, 1=right */)

    // ── Surface callback ──────────────────────────────────────────────

    val surfaceCallback = object : SurfaceCallback {
        override fun onSurfaceAvailable(container: SurfaceContainer) {
            surface = container.surface
            surfaceWidth = container.width
            surfaceHeight = container.height
            startAnimation()
        }

        override fun onSurfaceDestroyed(container: SurfaceContainer) {
            stopAnimation()
            surface = null
        }

        override fun onVisibleAreaChanged(visibleArea: Rect) {
            // Could adjust drawing bounds; using full surface for now
        }

        override fun onStableAreaChanged(stableArea: Rect) {}
    }

    // ── Animation loop ────────────────────────────────────────────────

    private fun startAnimation() {
        animJob?.cancel()
        animJob = scope.launch {
            while (isActive) {
                drawFrame()
                delay(33) // ~30 fps
            }
        }
    }

    private fun stopAnimation() {
        animJob?.cancel()
        animJob = null
    }

    private fun drawFrame() {
        val s = surface ?: return
        if (!s.isValid) return
        val w = surfaceWidth
        val h = surfaceHeight
        if (w <= 0 || h <= 0) return

        val canvas: Canvas = try { s.lockCanvas(null) } catch (_: Exception) { return }
        try {
            val px = 8 // pixel block size
            val speed = CarObd2DataHolder.speed

            // Scroll speed: base + OBD2 speed factor
            val scrollSpeed = 1f + (speed / 20f).coerceAtMost(8f)
            roadOffset = (roadOffset + scrollSpeed) % (px * 4f)

            // ── Black background
            canvas.drawColor(nesPalette[0])

            // ── Draw road with perspective
            drawRoad(canvas, w, h, px)

            // ── Draw trees/buildings on sides
            updateAndDrawTrees(canvas, w, h, px, scrollSpeed)

            // ── Draw pixel car sprite at bottom center
            drawCarSprite(canvas, w, h, px)

            // ── Draw speed readout
            drawSpeed(canvas, w, h, px, speed)

            // ── Draw title
            drawTitle(canvas, w, h, px)

        } finally {
            try { s.unlockCanvasAndPost(canvas) } catch (_: Exception) {}
        }
    }

    // ── Road drawing (perspective scrolling) ──────────────────────────

    private fun drawRoad(canvas: Canvas, w: Int, h: Int, px: Int) {
        val horizonY = h * 0.3f
        val roadRows = ((h - horizonY) / px).toInt()

        for (row in 0 until roadRows) {
            val y = horizonY + row * px
            val progress = row.toFloat() / roadRows // 0=horizon, 1=bottom

            // Road width expands toward bottom (perspective)
            val roadHalfWidth = (w * 0.05f + w * 0.35f * progress).roundToInt()
            val centerX = w / 2

            // Road surface — dark gray
            paint.color = nesPalette[5]
            canvas.drawRect(
                (centerX - roadHalfWidth).toFloat(), y,
                (centerX + roadHalfWidth).toFloat(), y + px,
                paint
            )

            // Road edge lines — yellow
            paint.color = nesPalette[10]
            val edgeW = (px * 0.5f * (0.3f + progress * 0.7f)).coerceAtLeast(1f)
            canvas.drawRect(
                centerX - roadHalfWidth.toFloat(), y,
                centerX - roadHalfWidth + edgeW, y + px,
                paint
            )
            canvas.drawRect(
                centerX + roadHalfWidth - edgeW, y,
                (centerX + roadHalfWidth).toFloat(), y + px,
                paint
            )

            // Center dashes — white, scrolling
            val dashCycle = (px * 4)
            val dashPos = ((row * px + roadOffset) % dashCycle).toInt()
            if (dashPos < dashCycle / 2) {
                paint.color = nesPalette[7]
                val dashW = (px * 0.4f * (0.2f + progress * 0.8f)).coerceAtLeast(1f)
                canvas.drawRect(
                    centerX - dashW, y,
                    centerX + dashW, y + px,
                    paint
                )
            }
        }
    }

    // ── Trees / buildings ─────────────────────────────────────────────

    private fun updateAndDrawTrees(canvas: Canvas, w: Int, h: Int, px: Int, scrollSpeed: Float) {
        // Spawn new trees occasionally
        if (rng.nextFloat() < 0.08f) {
            val side = if (rng.nextBoolean()) -1 else 1
            trees.add(TreeSprite(
                x = if (side == -1) w * 0.1f * rng.nextFloat() else w - w * 0.1f * rng.nextFloat(),
                y = h * 0.3f,
                side = side
            ))
        }

        val iterator = trees.iterator()
        while (iterator.hasNext()) {
            val tree = iterator.next()
            tree.y += scrollSpeed * 1.5f

            // Scale with Y position (perspective)
            val progress = ((tree.y - h * 0.3f) / (h * 0.7f)).coerceIn(0f, 1f)
            val size = (px * (1f + progress * 3f)).roundToInt()

            // Move outward as it comes closer
            val spreadX = if (tree.side == -1) {
                tree.x - progress * w * 0.15f
            } else {
                tree.x + progress * w * 0.15f
            }

            // Draw tree: trunk (brown) + canopy (green)
            paint.color = nesPalette[4] // brown trunk
            canvas.drawRect(
                spreadX - size * 0.15f, tree.y - size * 0.3f,
                spreadX + size * 0.15f, tree.y + size * 0.3f,
                paint
            )
            paint.color = nesPalette[3] // dark green canopy
            canvas.drawRect(
                spreadX - size * 0.5f, tree.y - size,
                spreadX + size * 0.5f, tree.y - size * 0.2f,
                paint
            )
            // Highlight
            paint.color = nesPalette[11] // bright green
            canvas.drawRect(
                spreadX - size * 0.3f, tree.y - size * 0.9f,
                spreadX + size * 0.1f, tree.y - size * 0.4f,
                paint
            )

            if (tree.y > h + size) iterator.remove()
        }

        // Cap tree count
        while (trees.size > 30) trees.removeFirst()
    }

    // ── Pixel art car sprite (~16×12 blocks) ──────────────────────────

    private fun drawCarSprite(canvas: Canvas, w: Int, h: Int, px: Int) {
        val carPx = (px * 0.6f).coerceAtLeast(3f)
        val startX = w / 2f - 8 * carPx
        val startY = h - 14 * carPx

        // Car body pixels (16 wide × 12 tall): 0=transparent, palette index otherwise
        val sprite = arrayOf(
            intArrayOf(0,0,0,0,0,12,12,12,12,12,0,0,0,0,0,0), // roof
            intArrayOf(0,0,0,0,12,12,12,12,12,12,12,0,0,0,0,0),
            intArrayOf(0,0,0,12,12, 1, 1, 1, 1,12,12,12,0,0,0,0), // windshield
            intArrayOf(0,0,12,12, 1, 1, 1, 1, 1, 1,12,12,12,0,0,0),
            intArrayOf(0,12,12,12,12,12,12,12,12,12,12,12,12,12,0,0), // hood
            intArrayOf(0,12,12,12,12,12,12,12,12,12,12,12,12,12,0,0),
            intArrayOf(8,12,12,12,12,12,12,12,12,12,12,12,12,12,8,0), // body + lights
            intArrayOf(8,12,12,12,12,12,12,12,12,12,12,12,12,12,8,0),
            intArrayOf(0,12,12,12,12,12,12,12,12,12,12,12,12,12,0,0),
            intArrayOf(0,0,5,5,12,12,12,12,12,12,12,12,5,5,0,0),   // undercarriage
            intArrayOf(0,5,5,5,5,0,0,0,0,0,0,5,5,5,5,0),           // wheels
            intArrayOf(0,0,5,5,0,0,0,0,0,0,0,0,5,5,0,0),
        )

        for (row in sprite.indices) {
            for (col in sprite[row].indices) {
                val colorIdx = sprite[row][col]
                if (colorIdx == 0) continue
                paint.color = nesPalette[colorIdx]
                canvas.drawRect(
                    startX + col * carPx, startY + row * carPx,
                    startX + (col + 1) * carPx, startY + (row + 1) * carPx,
                    paint
                )
            }
        }
    }

    // ── Speed readout in chunky pixel font ────────────────────────────

    private fun drawSpeed(canvas: Canvas, w: Int, h: Int, px: Int, speed: Float) {
        val speedStr = "%.0f".format(speed)
        val blockSize = px * 2f
        val totalWidth = speedStr.length * 6 * blockSize // 5 wide + 1 gap per char
        val startX = w - totalWidth - px * 4
        val startY = h - px * 16f

        // "KM/H" label
        paint.color = nesPalette[6]
        // Just draw as solid text approximation — small blocks
        val labelPx = px * 0.8f
        drawPixelString("KMH", (w - 4 * 6 * labelPx - px * 4), startY + 6 * blockSize, labelPx, nesPalette[6], canvas)

        for ((i, ch) in speedStr.withIndex()) {
            val bitmap = pixelDigits[ch] ?: continue
            val cx = startX + i * 6 * blockSize
            for (bit in bitmap.indices) {
                if (bitmap[bit] == 0) continue
                val col = bit % 5
                val row = bit / 5
                paint.color = nesPalette[11] // bright green digits
                canvas.drawRect(
                    cx + col * blockSize, startY + row * blockSize,
                    cx + (col + 1) * blockSize, startY + (row + 1) * blockSize,
                    paint
                )
            }
        }
    }

    private fun drawPixelString(text: String, x: Float, y: Float, blockSize: Float, color: Int, canvas: Canvas) {
        for ((i, ch) in text.withIndex()) {
            val bitmap = pixelLetters[ch] ?: continue
            val cx = x + i * 6 * blockSize
            for (bit in bitmap.indices) {
                if (bitmap[bit] == 0) continue
                val col = bit % 5
                val row = bit / 5
                paint.color = color
                canvas.drawRect(
                    cx + col * blockSize, y + row * blockSize,
                    cx + (col + 1) * blockSize, y + (row + 1) * blockSize,
                    paint
                )
            }
        }
    }

    // ── Title: "TRICORDER PRIME" ──────────────────────────────────────

    private fun drawTitle(canvas: Canvas, w: Int, h: Int, px: Int) {
        val blockSize = px * 1.2f
        val totalWidth = titleText.length * 6 * blockSize
        val startX = (w - totalWidth) / 2f
        val startY = px * 2f

        drawPixelString(titleText, startX, startY, blockSize, nesPalette[12], canvas)
    }

    // ── Template ──────────────────────────────────────────────────────

    override fun onGetTemplate(): Template {
        return NavigationTemplate.Builder()
            .setActionStrip(
                ActionStrip.Builder()
                    .addAction(
                        Action.Builder()
                            .setTitle("OBD2")
                            .setOnClickListener { screenManager.pop() }
                            .build()
                    )
                    .build()
            )
            .build()
    }

}
