// Minimal Vision OCR helper for the console watcher.
//
// Why Swift: macOS ships Vision and it needs no installs, whereas tesseract would be a brew
// dependency and the Python Vision bindings (pyobjc) are not present on this machine.
//
// Output is one JSON object per recognised line so the caller never has to parse prose.
//   [{"text":"...","conf":0.93,"x":0.1,"y":0.2,"w":0.3,"h":0.05}, ...]
// Coordinates are normalised, origin bottom-left (Vision's convention).

import Foundation
import Vision
import AppKit

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(2)
}

let args = CommandLine.arguments
guard args.count > 1 else { fail("usage: ocr <image-path>") }
let path = args[1]

guard let image = NSImage(contentsOfFile: path),
      let tiff = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let cg = rep.cgImage else {
    fail("cannot load image: \(path)")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    fail("vision failed: \(error)")
}

var out: [[String: Any]] = []
for obs in (request.results ?? []) {
    guard let candidate = obs.topCandidates(1).first else { continue }
    let b = obs.boundingBox
    out.append([
        "text": candidate.string,
        "conf": Double(candidate.confidence),
        "x": Double(b.origin.x),
        "y": Double(b.origin.y),
        "w": Double(b.size.width),
        "h": Double(b.size.height),
    ])
}

let data = try JSONSerialization.data(withJSONObject: out, options: [])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
