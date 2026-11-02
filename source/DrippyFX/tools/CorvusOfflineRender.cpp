/*
    Corvus offline demo renderer (CV-033).

    This one shared main is compiled into two console executables:

        CorvusRenderFX         -> CorvusFXAudioProcessor
        CorvusRenderInstrument -> CorvusInstrumentProcessor

    Each executable links exactly one real product processor (and its
    createPluginFilter factory), so the generated audio goes through the
    product's actual AudioProcessor::processBlock path and its public
    setCurrentProgram()/getProgramName() interface. No DSP is copied here.

    Fixed render contract:
      * 48000 Hz, stereo, 24-bit PCM WAV.
      * 512-sample blocks; the final block is shortened as needed.
      * --seconds is bounded to 0.25 .. 30.0 (default 6.0).
      * No audio device, host, microphone, user input file, network, provider
        or model is touched. Input is generated procedurally in this file.

    Output honesty:
      * The render is written to "<out>.partial" and only moved into place
        after the WAV has been reopened and checked for format and length.
      * Non-finite output fails the render; it is never replaced with silence.
      * An all-silent render fails the render.
      * Samples outside [-1, 1] are reported because 24-bit PCM cannot carry
        them; the tool does not change the product's gain to hide that.
      * An existing output file is never replaced without --overwrite.
*/

#include <JuceHeader.h>

#if defined(CORVUS_RENDER_PRODUCT_FX) && defined(CORVUS_RENDER_PRODUCT_INSTRUMENT)
    #error "Define exactly one of CORVUS_RENDER_PRODUCT_FX or CORVUS_RENDER_PRODUCT_INSTRUMENT"
#endif

#if defined(CORVUS_RENDER_PRODUCT_FX)
    #include "../PluginProcessor.h"
    using ProductProcessor = CorvusFXAudioProcessor;
    static constexpr const char* kProductName = "Corvus FX";
    static constexpr const char* kInputDescription =
        "original deterministic procedural tone/transient bed";
#elif defined(CORVUS_RENDER_PRODUCT_INSTRUMENT)
    #include "../instrument/CorvusInstrumentProcessor.h"
    using ProductProcessor = CorvusInstrumentProcessor;
    static constexpr const char* kProductName = "Corvus Instrument";
    static constexpr const char* kInputDescription =
        "original deterministic bounded MIDI chord pattern";
#else
    #error "Define CORVUS_RENDER_PRODUCT_FX or CORVUS_RENDER_PRODUCT_INSTRUMENT"
#endif

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <memory>
#include <vector>

namespace
{
constexpr double kSampleRate = 48000.0;
constexpr int kNumChannels = 2;
constexpr int kBitsPerSample = 24;
constexpr int kBlockSize = 512;
constexpr double kDefaultSeconds = 6.0;
constexpr double kMinSeconds = 0.25;
constexpr double kMaxSeconds = 30.0;
constexpr std::int64_t kMaxFrames = 1440000; // 30 s at 48 kHz

struct Options
{
    bool help = false;
    bool listPresets = false;
    bool overwrite = false;
    int preset = -1;
    juce::String outPath;
    double seconds = kDefaultSeconds;
    juce::String provenance;
};

void writeOut (const juce::String& text)
{
    std::cout << text.toRawUTF8() << '\n';
}

void writeErr (const juce::String& text)
{
    std::cerr << text.toRawUTF8() << '\n';
}

void printUsage (const juce::String& appName)
{
    juce::String usage;
    usage << "Corvus offline demo renderer (CV-033)\n"
          << "\n"
          << "Usage:\n"
          << "  " << appName << " --list-presets\n"
          << "  " << appName << " --preset <index> --out <new.wav> [options]\n"
          << "\n"
          << "Required for rendering:\n"
          << "  --preset <index>      Program index from --list-presets (0-based)\n"
          << "  --out <path.wav>      New output path. An existing file is refused\n"
          << "                        unless --overwrite is also given.\n"
          << "\n"
          << "Options:\n"
          << "  --seconds <n>         Render length, 0.25 to 30.0 (default 6.0)\n"
          << "  --provenance <text>   Echo this text in the report, e.g. a git revision\n"
          << "  --overwrite           Replace an existing --out file (and stale .partial)\n"
          << "  --list-presets        Print program indices and names, then exit\n"
          << "  --help, -h            Print this help, then exit\n"
          << "\n"
          << "Fixed output: 48000 Hz, stereo, 24-bit PCM WAV, 512-sample blocks.\n"
          << "Exit codes: 0 success, 1 render/writer/verification failure,\n"
          << "            2 usage error or output-path precondition.\n";
    writeOut (usage);
}

int usageError (const juce::String& appName, const juce::String& message)
{
    writeErr ("error: " + message);
    writeOut (juce::String());
    printUsage (appName);
    return 2;
}

bool parseNonNegativeInt (const juce::String& text, int& value)
{
    const auto trimmed = text.trim();
    if (trimmed.isEmpty())
        return false;

    int result = 0;
    for (auto character : trimmed)
    {
        if (character < '0' || character > '9')
            return false;

        if (result > 1000000)
            return false;

        result = result * 10 + static_cast<int> (character - '0');
    }

    value = result;
    return true;
}

bool parseFiniteDouble (const juce::String& text, double& value)
{
    const auto trimmed = text.trim();
    if (trimmed.isEmpty())
        return false;

    const char* raw = trimmed.toRawUTF8();
    char* end = nullptr;
    errno = 0;
    const double parsed = std::strtod (raw, &end);

    if (end == raw || end == nullptr || *end != '\0' || errno == ERANGE)
        return false;

    if (! std::isfinite (parsed))
        return false;

    value = parsed;
    return true;
}

bool parseOptions (int argc, char* argv[], Options& options, juce::String& error)
{
    for (int i = 1; i < argc; ++i)
    {
        const juce::String argument (argv[i]);

        auto takeValue = [&] (juce::String& destination) -> bool
        {
            if (i + 1 >= argc)
            {
                error = "missing value after " + argument;
                return false;
            }

            destination = juce::String (argv[++i]);
            return true;
        };

        if (argument == "--help" || argument == "-h")
        {
            options.help = true;
        }
        else if (argument == "--list-presets")
        {
            options.listPresets = true;
        }
        else if (argument == "--overwrite")
        {
            options.overwrite = true;
        }
        else if (argument == "--preset")
        {
            juce::String value;
            if (! takeValue (value))
                return false;

            if (! parseNonNegativeInt (value, options.preset))
            {
                error = "--preset expects a non-negative integer, got '" + value + "'";
                return false;
            }
        }
        else if (argument == "--seconds")
        {
            juce::String value;
            if (! takeValue (value))
                return false;

            double parsed = 0.0;
            if (! parseFiniteDouble (value, parsed))
            {
                error = "--seconds expects a finite number, got '" + value + "'";
                return false;
            }

            options.seconds = parsed;
        }
        else if (argument == "--out")
        {
            if (! takeValue (options.outPath))
                return false;
        }
        else if (argument == "--provenance")
        {
            if (! takeValue (options.provenance))
                return false;
        }
        else
        {
            error = "unknown argument '" + argument + "'";
            return false;
        }
    }

    return true;
}

bool checkOutputPath (const Options& options,
                      const juce::File& outFile,
                      juce::File& tempFile,
                      juce::String& error)
{
    if (outFile.getFullPathName().isEmpty())
    {
        error = "--out is empty";
        return false;
    }

    if (outFile.isDirectory())
    {
        error = "--out points at a directory: " + outFile.getFullPathName();
        return false;
    }

    if (! outFile.hasFileExtension ("wav"))
    {
        error = "--out must end in .wav: " + outFile.getFullPathName();
        return false;
    }

    const auto parent = outFile.getParentDirectory();
    if (! parent.isDirectory())
    {
        error = "output directory does not exist: " + parent.getFullPathName();
        return false;
    }

    if (! parent.hasWriteAccess())
    {
        error = "output directory is not writable: " + parent.getFullPathName();
        return false;
    }

    if (outFile.existsAsFile() && ! options.overwrite)
    {
        error = "refusing to overwrite existing file: " + outFile.getFullPathName()
              + " (pass --overwrite to replace it)";
        return false;
    }

    if (outFile.existsAsFile() && ! outFile.hasWriteAccess())
    {
        error = "existing output file is not writable: " + outFile.getFullPathName();
        return false;
    }

    tempFile = outFile.getSiblingFile (outFile.getFileName() + ".partial");

    if (tempFile.existsAsFile())
    {
        if (! options.overwrite)
        {
            error = "refusing to overwrite stale partial file: " + tempFile.getFullPathName()
                  + " (pass --overwrite to replace it)";
            return false;
        }

        if (! tempFile.deleteFile())
        {
            error = "could not delete stale partial file: " + tempFile.getFullPathName();
            return false;
        }
    }

    return true;
}

#if defined(CORVUS_RENDER_PRODUCT_FX)
// Original deterministic tone/transient bed. Phase comes from the absolute
// frame index, so the signal is independent of the block split. There is no
// PRNG and no sample-rate conversion.
constexpr double kTwoPi = 6.283185307179586476925286766559;

void fillFxInput (juce::AudioBuffer<float>& buffer, std::int64_t startFrame)
{
    const int numSamples = buffer.getNumSamples();

    for (int i = 0; i < numSamples; ++i)
    {
        const double t = static_cast<double> (startFrame + i) / kSampleRate;

        // 10 ms fade-in so the bed does not start with a step.
        const double fadeIn = std::min (1.0, t / 0.010);

        double left  = 0.16 * std::sin (kTwoPi * 110.0 * t)
                     + 0.10 * std::sin (kTwoPi * 165.0 * t + 0.4)
                     + 0.05 * std::sin (kTwoPi * 220.0 * t + 1.1);
        double right = 0.16 * std::sin (kTwoPi * 110.4 * t + 0.2)
                     + 0.10 * std::sin (kTwoPi * 164.6 * t + 0.9)
                     + 0.05 * std::sin (kTwoPi * 220.7 * t + 1.7);

        left *= fadeIn;
        right *= fadeIn;

        // One short decaying transient every 500 ms, starting exactly at the
        // periodic boundary (the sine is zero there, so there is no click).
        const double phase = std::fmod (t, 0.5);
        if (phase < 0.12)
        {
            const double envelope = std::exp (-phase * 38.0);
            const double burst = 0.28 * envelope * std::sin (kTwoPi * 1800.0 * phase);
            left += burst;
            right += burst * 0.9;
        }

        buffer.setSample (0, i, static_cast<float> (left));
        buffer.setSample (1, i, static_cast<float> (right));
    }
}
#else
// Original bounded MIDI phrase: four triads, each held for 0.6 s with a 0.6 s
// gap before the next one. Last note-off is at 4.2 s; the rest of the render is
// release tail, so a render of at least ~4.5 s exercises note-off behaviour.
struct ScheduledMidiEvent
{
    std::int64_t frame = 0;
    int note = 0;
    bool noteOn = false;
};

std::vector<ScheduledMidiEvent> makeInstrumentPattern()
{
    static constexpr int chords[4][3] =
    {
        { 57, 60, 64 }, // A minor
        { 53, 57, 60 }, // F major
        { 48, 52, 55 }, // C major
        { 55, 59, 62 }  // G major
    };

    std::vector<ScheduledMidiEvent> events;
    events.reserve (4 * 3 * 2);

    for (int chord = 0; chord < 4; ++chord)
    {
        const auto onFrame = static_cast<std::int64_t> (std::llround (chord * 1.2 * kSampleRate));
        const auto offFrame = onFrame + static_cast<std::int64_t> (std::llround (0.6 * kSampleRate));

        for (int note : chords[chord])
        {
            events.push_back ({ onFrame, note, true });
            events.push_back ({ offFrame, note, false });
        }
    }

    std::stable_sort (events.begin(), events.end(),
                      [] (const ScheduledMidiEvent& a, const ScheduledMidiEvent& b)
                      {
                          return a.frame < b.frame;
                      });

    return events;
}

void addInstrumentMidiForBlock (juce::MidiBuffer& midi,
                                std::size_t& nextEvent,
                                const std::vector<ScheduledMidiEvent>& events,
                                std::int64_t startFrame,
                                int numSamples)
{
    const auto endFrame = startFrame + numSamples;

    while (nextEvent < events.size() && events[nextEvent].frame < endFrame)
    {
        const auto& event = events[nextEvent];

        if (event.frame >= startFrame)
        {
            const int samplePosition = static_cast<int> (event.frame - startFrame);
            const auto message = event.noteOn
                ? juce::MidiMessage::noteOn (1, event.note, 0.8f)
                : juce::MidiMessage::noteOff (1, event.note);

            midi.addEvent (message, samplePosition);
        }

        ++nextEvent;
    }
}
#endif

bool verifyWavFile (const juce::File& file, std::int64_t expectedFrames, juce::String& error)
{
    auto stream = file.createInputStream();
    if (stream == nullptr || ! stream->openedOk())
    {
        error = "could not reopen the rendered file for verification: " + file.getFullPathName();
        return false;
    }

    juce::WavAudioFormat wavFormat;
    std::unique_ptr<juce::AudioFormatReader> reader (wavFormat.createReaderFor (stream.release(), true));

    if (reader == nullptr)
    {
        error = "the rendered file could not be read back as WAV: " + file.getFullPathName();
        return false;
    }

    if (reader->numChannels != static_cast<unsigned int> (kNumChannels))
    {
        error = "verification failed: channels=" + juce::String (static_cast<int> (reader->numChannels))
              + ", expected " + juce::String (kNumChannels);
        return false;
    }

    if (reader->bitsPerSample != static_cast<unsigned int> (kBitsPerSample))
    {
        error = "verification failed: bits_per_sample=" + juce::String (static_cast<int> (reader->bitsPerSample))
              + ", expected " + juce::String (kBitsPerSample);
        return false;
    }

    if (std::abs (reader->sampleRate - kSampleRate) > 0.5)
    {
        error = "verification failed: sample_rate=" + juce::String (reader->sampleRate, 3)
              + ", expected " + juce::String (kSampleRate, 3);
        return false;
    }

    if (reader->lengthInSamples != expectedFrames)
    {
        error = "verification failed: frames=" + juce::String (reader->lengthInSamples)
              + ", expected " + juce::String (static_cast<juce::int64> (expectedFrames));
        return false;
    }

    return true;
}

juce::String formatDb (double linear)
{
    return juce::String (juce::Decibels::gainToDecibels (linear, -200.0), 2);
}

// Bit-level finiteness check. The targets compile with the product's
// floating-point flags (MSVC /fp:fast), so a compiler is allowed to fold an
// isfinite() test on arithmetic paths. Inspecting the IEEE-754 exponent bits
// keeps the honesty gate value-dependent on the opaque processBlock output.
bool isFiniteFloat (float value) noexcept
{
    static_assert (sizeof (float) == sizeof (std::uint32_t), "IEEE-754 float expected");

    std::uint32_t bits = 0;
    std::memcpy (&bits, &value, sizeof (bits));
    return (bits & 0x7f800000u) != 0x7f800000u;
}

int renderToFile (ProductProcessor& processor,
                  const Options& options,
                  std::int64_t frames,
                  const juce::File& outFile,
                  const juce::File& tempFile,
                  const juce::String& programName)
{
    // Declared before the writer so it is destroyed last: any exception path
    // still closes the writer first, then removes an unfinished .partial file.
    struct TempFileCleanup
    {
        const juce::File& file;
        ~TempFileCleanup()
        {
            if (file.existsAsFile())
                file.deleteFile();
        }
    } tempCleanup { tempFile };

    std::unique_ptr<juce::OutputStream> stream;
    std::unique_ptr<juce::AudioFormatWriter> writer;

    auto fail = [&] (const juce::String& message) -> int
    {
        writer.reset();
        stream.reset();

        if (tempFile.existsAsFile())
            tempFile.deleteFile();

        writeErr ("render failed: " + message);
        writeErr ("no new output file was kept");
        return 1;
    };

    // A host supplies these before prepareToPlay. The products here read the
    // prepared rate/block size from their own members rather than
    // getSampleRate()/getBlockSize(), but publishing them keeps the render
    // path host-shaped instead of relying on that detail.
    processor.setRateAndBufferSizeDetails (kSampleRate, kBlockSize);
    processor.prepareToPlay (kSampleRate, kBlockSize);

    struct ReleaseGuard
    {
        ProductProcessor& processor;
        ~ReleaseGuard() { processor.releaseResources(); }
    } releaseGuard { processor };

    auto fileStream = std::make_unique<juce::FileOutputStream> (tempFile);
    if (! fileStream->openedOk())
    {
        const auto status = fileStream->getStatus().getErrorMessage();
        fileStream.reset();
        return fail ("could not open temporary output " + tempFile.getFullPathName()
                   + ": " + status);
    }

    stream = std::move (fileStream);

    juce::WavAudioFormat wavFormat;
    writer = wavFormat.createWriterFor (stream, juce::AudioFormatWriterOptions {}
        .withSampleRate (kSampleRate)
        .withNumChannels (kNumChannels)
        .withBitsPerSample (kBitsPerSample));

    if (writer == nullptr)
        return fail ("WAV writer could not be created for 48 kHz / stereo / 24-bit");

    juce::AudioBuffer<float> block (kNumChannels, kBlockSize);
    juce::MidiBuffer midi;

#if ! defined(CORVUS_RENDER_PRODUCT_FX)
    std::size_t nextMidiEvent = 0;
    const auto midiEvents = makeInstrumentPattern();
#endif

    double peak[kNumChannels] = {};
    double sumOfSquares[kNumChannels] = {};
    std::int64_t clipped[kNumChannels] = {};
    std::int64_t frame = 0;

    while (frame < frames)
    {
        const int numSamples = static_cast<int> (std::min<std::int64_t> (kBlockSize, frames - frame));
        block.setSize (kNumChannels, numSamples, false, false, true);
        midi.clear();

#if defined(CORVUS_RENDER_PRODUCT_FX)
        fillFxInput (block, frame);
#else
        block.clear();
        addInstrumentMidiForBlock (midi, nextMidiEvent, midiEvents, frame, numSamples);
#endif

        processor.processBlock (block, midi);

        // Inspect the real product output before it reaches the file. Never
        // sanitize a bad sample: report it and fail instead.
        for (int channel = 0; channel < kNumChannels; ++channel)
        {
            const float* samples = block.getReadPointer (channel);

            for (int i = 0; i < numSamples; ++i)
            {
                const float value = samples[i];

                if (! isFiniteFloat (value))
                {
                    return fail ("non-finite output sample: frame="
                               + juce::String (static_cast<juce::int64> (frame + i))
                               + " channel=" + juce::String (channel)
                               + " value=" + juce::String (static_cast<double> (value)));
                }

                const double magnitude = std::abs (static_cast<double> (value));
                peak[channel] = std::max (peak[channel], magnitude);
                sumOfSquares[channel] += static_cast<double> (value) * static_cast<double> (value);

                if (magnitude > 1.0)
                    ++clipped[channel];
            }
        }

        if (! writer->writeFromAudioSampleBuffer (block, 0, numSamples))
        {
            return fail ("WAV writer rejected the block starting at frame "
                       + juce::String (static_cast<juce::int64> (frame)));
        }

        frame += numSamples;
    }

    if (! writer->flush())
        return fail ("the WAV writer could not flush the output");

    writer.reset();
    stream.reset();

    const double overallPeak = std::max (peak[0], peak[1]);
    if (overallPeak <= 0.0)
    {
        return fail ("the product rendered 100% silence for program "
                   + juce::String (options.preset) + " (" + programName + ")");
    }

    juce::String verificationError;
    if (! verifyWavFile (tempFile, frames, verificationError))
        return fail (verificationError);

    if (outFile.existsAsFile() && ! options.overwrite)
    {
        return fail ("refusing to overwrite a file that appeared during rendering: "
                   + outFile.getFullPathName());
    }

    if (! tempFile.moveFileTo (outFile))
        return fail ("could not move the verified WAV into place: " + outFile.getFullPathName());

    const double rmsLeft = std::sqrt (sumOfSquares[0] / static_cast<double> (frames));
    const double rmsRight = std::sqrt (sumOfSquares[1] / static_cast<double> (frames));
    const double overallRms = std::sqrt ((sumOfSquares[0] + sumOfSquares[1])
                                      / static_cast<double> (frames * kNumChannels));
    const auto clippedTotal = clipped[0] + clipped[1];

    writeOut ("wrote=" + outFile.getFullPathName());
    writeOut ("product=" + juce::String (kProductName));
    writeOut ("processor_name=" + processor.getName());
    writeOut ("program=" + juce::String (options.preset));
    writeOut ("program_name=" + programName);
    writeOut ("current_program=" + juce::String (processor.getCurrentProgram()));
    writeOut ("frames=" + juce::String (static_cast<juce::int64> (frames)));
    writeOut ("samples_per_channel=" + juce::String (static_cast<juce::int64> (frames)));
    writeOut ("total_samples=" + juce::String (static_cast<juce::int64> (frames * kNumChannels)));
    writeOut ("duration_seconds=" + juce::String (static_cast<double> (frames) / kSampleRate, 6));
    writeOut ("peak_linear=" + juce::String (overallPeak, 6));
    writeOut ("peak_dbfs=" + formatDb (overallPeak)
            + " (left=" + formatDb (peak[0]) + ", right=" + formatDb (peak[1]) + ")");
    writeOut ("rms_linear=" + juce::String (overallRms, 6));
    writeOut ("rms_dbfs=" + formatDb (overallRms)
            + " (left=" + formatDb (rmsLeft) + ", right=" + formatDb (rmsRight) + ")");
    writeOut ("clipped_samples=" + juce::String (static_cast<juce::int64> (clippedTotal))
            + " (left=" + juce::String (static_cast<juce::int64> (clipped[0]))
            + ", right=" + juce::String (static_cast<juce::int64> (clipped[1])) + ")");
    writeOut ("provenance=" + (options.provenance.isNotEmpty()
                               ? options.provenance
                               : juce::String ("(not supplied)")));
    writeOut ("juce=" + juce::SystemStats::getJUCEVersion());
    writeOut ("readback=verified");
    writeOut ("status=ok");

    if (clippedTotal > 0)
    {
        writeErr ("warning: " + juce::String (static_cast<juce::int64> (clippedTotal))
                + " rendered sample(s) were outside [-1.0, +1.0]; 24-bit PCM cannot"
                  " carry them, so the WAV will clip or distort them. The tool does"
                  " not change the product's gain.");
    }

    return 0;
}

int run (int argc, char* argv[])
{
    const auto appName = juce::File::getSpecialLocation (juce::File::currentExecutableFile)
                             .getFileNameWithoutExtension();

    Options options;
    juce::String parseError;
    if (! parseOptions (argc, argv, options, parseError))
        return usageError (appName, parseError);

    if (options.help)
    {
        printUsage (appName);
        return 0;
    }

    // The FX processor owns large fixed DSP delay/reverb buffers. Keeping it
    // on a Windows console's default stack overflows before even --help can
    // run. Own the unchanged real processor on the heap for both products.
    auto processorOwner = std::make_unique<ProductProcessor>();
    auto& processor = *processorOwner;
    const int numPrograms = processor.getNumPrograms();

    if (numPrograms <= 0)
    {
        writeErr ("render failed: the product reports no programs");
        return 1;
    }

    if (options.listPresets)
    {
        writeOut ("product=" + juce::String (kProductName));
        writeOut ("program_count=" + juce::String (numPrograms));

        for (int i = 0; i < numPrograms; ++i)
        {
            const auto name = processor.getProgramName (i);
            writeOut (juce::String (i) + "\t" + (name.isNotEmpty()
                                                ? name
                                                : juce::String ("(empty)")));
        }

        return 0;
    }

    if (options.preset < 0)
        return usageError (appName, "missing --preset <index> (use --list-presets to see indices)");

    if (options.preset >= numPrograms)
    {
        return usageError (appName, "--preset " + juce::String (options.preset)
                                    + " is outside the product range 0.."
                                    + juce::String (numPrograms - 1));
    }

    if (options.outPath.trim().isEmpty())
        return usageError (appName, "missing --out <new .wav path>");

    if (! (options.seconds >= kMinSeconds && options.seconds <= kMaxSeconds))
    {
        return usageError (appName, "--seconds " + juce::String (options.seconds, 6)
                                    + " is outside " + juce::String (kMinSeconds, 2)
                                    + ".." + juce::String (kMaxSeconds, 1));
    }

    const auto frames = static_cast<std::int64_t> (std::llround (options.seconds * kSampleRate));
    if (frames <= 0 || frames > kMaxFrames)
    {
        return usageError (appName, "requested length is outside the bounded sample count");
    }

    juce::File outFile (options.outPath.trim());
    juce::File tempFile;
    juce::String outputError;
    if (! checkOutputPath (options, outFile, tempFile, outputError))
        return usageError (appName, outputError);

    const auto programName = processor.getProgramName (options.preset);
    if (programName.isEmpty())
    {
        writeErr ("render failed: program " + juce::String (options.preset)
                + " has no name");
        return 1;
    }

    processor.setCurrentProgram (options.preset);
    if (processor.getCurrentProgram() != options.preset)
    {
        writeErr ("render failed: setCurrentProgram(" + juce::String (options.preset)
                + ") did not take effect; getCurrentProgram() returned "
                + juce::String (processor.getCurrentProgram()));
        return 1;
    }

    writeOut ("product=" + juce::String (kProductName));
    writeOut ("program=" + juce::String (options.preset));
    writeOut ("program_name=" + programName);
    writeOut ("current_program=" + juce::String (processor.getCurrentProgram()));
    writeOut ("input=" + juce::String (kInputDescription));
    writeOut ("sample_rate=" + juce::String (static_cast<int> (kSampleRate)));
    writeOut ("channels=" + juce::String (kNumChannels));
    writeOut ("bits_per_sample=" + juce::String (kBitsPerSample));
    writeOut ("block_size=" + juce::String (kBlockSize));
    writeOut ("seconds=" + juce::String (options.seconds, 6));
    writeOut ("frames=" + juce::String (static_cast<juce::int64> (frames)));
    writeOut ("out=" + outFile.getFullPathName());
    writeOut ("provenance=" + (options.provenance.isNotEmpty()
                               ? options.provenance
                               : juce::String ("(not supplied)")));
    writeOut ("juce=" + juce::SystemStats::getJUCEVersion());

#if ! defined(CORVUS_RENDER_PRODUCT_FX)
    if (frames < static_cast<std::int64_t> (std::llround (4.5 * kSampleRate)))
    {
        writeErr ("warning: render is shorter than the 4.5 s instrument phrase;"
                  " note-offs and release tail may be truncated");
    }
#endif

    return renderToFile (processor, options, frames, outFile, tempFile, programName);
}
} // namespace

int main (int argc, char* argv[])
{
    try
    {
        return run (argc, argv);
    }
    catch (const std::exception& exception)
    {
        writeErr (juce::String ("render failed: unhandled exception: ") + exception.what());
        return 1;
    }
    catch (...)
    {
        writeErr ("render failed: unhandled non-standard exception");
        return 1;
    }
}
