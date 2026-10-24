// Local-only text recognition. No network, model downloads, or image persistence.
import Foundation
import Vision
import ImageIO

func emit(_ value: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let supported = try request.supportedRecognitionLanguages()
    request.recognitionLanguages = ["zh-Hans", "en-US"].filter { supported.contains($0) }
    let args = CommandLine.arguments
    if args.count == 2 && args[1] == "--check" {
        try emit(["available": !request.recognitionLanguages.isEmpty, "engine": "Apple Vision"])
    } else if args.count == 3 && args[1] == "--image" {
        let url = URL(fileURLWithPath: args[2])
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw NSError(domain: "BodyJournalOCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot decode image"])
        }
        let width = Double(image.width), height = Double(image.height)
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        let tokens = try NSRegularExpression(pattern: "\\S+")
        var lines: [(Double, [String: Any])] = []
        for observation in request.results ?? [] {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let text = candidate.string
            var words: [[String: Any]] = []
            for match in tokens.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                guard let range = Range(match.range, in: text) else { continue }
                let box = (try candidate.boundingBox(for: range))?.boundingBox ?? observation.boundingBox
                words.append(["text": String(text[range]), "x": Double(box.minX) * width,
                              "y": (1 - Double(box.maxY)) * height,
                              "width": Double(box.width) * width, "height": Double(box.height) * height])
            }
            lines.append((Double(observation.boundingBox.maxY), ["text": text, "words": words]))
        }
        lines.sort { $0.0 > $1.0 }
        try emit(["width": width, "height": height, "engine": "Apple Vision", "lines": lines.map { $0.1 }])
    } else {
        throw NSError(domain: "BodyJournalOCR", code: 2, userInfo: [NSLocalizedDescriptionKey: "Expected --check or --image path"])
    }
} catch {
    try? emit(["error": error.localizedDescription])
    exit(1)
}
