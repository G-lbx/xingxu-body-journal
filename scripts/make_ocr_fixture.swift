// Fictional test image generated on the CI runner; no user's report is uploaded.
import AppKit
import Foundation

let width = 1200, height = 1800
let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                             bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                             isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
NSColor.white.setFill()
NSRect(x: 0, y: 0, width: width, height: height).fill()
func draw(_ text: String, _ x: Int, _ top: Int, _ size: CGFloat = 38) {
    (text as NSString).draw(at: NSPoint(x: x, y: height-top-60), withAttributes: [
        .font: NSFont.systemFont(ofSize: size), .foregroundColor: NSColor.black])
}
draw("Body index", 450, 60)
draw("2024-01-20 08:00", 400, 130)
draw("Current weight (kg)", 60, 240)
draw("75.25", 60, 310, 68)
draw("BMI", 60, 530); draw("Standard weight", 660, 530)
draw("24.6", 60, 610, 50); draw("68 kg", 660, 610, 50)
draw("Bfp", 60, 800); draw("Fat weight", 660, 800)
draw("20.1%", 60, 880, 50); draw("15.1 kg", 660, 880, 50)
draw("Muscle", 60, 1070); draw("Water", 660, 1070)
draw("55.2 kg", 60, 1150, 50); draw("41.6 kg", 660, 1150, 50)
NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
