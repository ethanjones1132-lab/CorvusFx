cmake_minimum_required(VERSION 3.15)

project(DrippyFX VERSION 1.0.0)

# C++ Standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add JUCE
# You need to download JUCE from https://github.com/juce-framework/JUCE
# and set JUCE_PATH to the JUCE directory
set(JUCE_PATH "C:/Users/ethan/Downloads/juce-8.0.12-windows/JUCE" CACHE PATH "Path to JUCE framework")

if(NOT EXISTS "${JUCE_PATH}/modules")
    message(FATAL_ERROR "JUCE not found at ${JUCE_PATH}. Please download JUCE and set JUCE_PATH")
endif()

add_subdirectory(${JUCE_PATH} JUCE)

option(CORVUS_COPY_PLUGIN_AFTER_BUILD
    "Copy built VST3 bundles to the system plug-in directory"
    OFF
)

option(CORVUS_ENABLE_PGO
    "Enable profile-guided optimization. Two-pass workflow; see README build section."
    OFF
)

if(CORVUS_ENABLE_PGO)
    if(MSVC)
        add_compile_options(/GL)
    endif()
    message(STATUS "Corvus PGO: instrumentation flags enabled. Run the training executable before an optimize pass.")
endif()

# Plugin configuration
juce_add_plugin(DrippyFX
    COMPANY_NAME "DrippyFX"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD ${CORVUS_COPY_PLUGIN_AFTER_BUILD}
    PLUGIN_MANUFACTURER_CODE Drip
    PLUGIN_CODE Dfx1
    FORMATS VST3 AU Standalone
    # v1.0.0 buyer-facing product name (CV-034): the built Windows bundle is
    # "Corvus FX.vst3" and hosts see "Corvus FX" via the JUCE-generated
    # JucePlugin_Name. Bundle identity is unaffected by this rename: with no
    # explicit BUNDLE_ID here, JUCE derives the bundle ID from COMPANY_NAME
    # plus the CMake target name (see JUCE docs/CMake API.md), both still
    # "DrippyFX", and the VST3 class IDs come from the stable
    # PLUGIN_MANUFACTURER_CODE/PLUGIN_CODE below. Do not add a BUNDLE_ID here
    # without an approved identity decision; do not rename the target.
    PRODUCT_NAME "Corvus FX"
    VST3_CATEGORIES "Fx" "Dynamics" "Modulation" "Reverb" "Delay"
)

juce_generate_juce_header(DrippyFX)

# Source files
target_sources(DrippyFX
    PRIVATE
        PluginEditor.cpp
        PluginProcessor.cpp
)

# Compile definitions
target_compile_definitions(DrippyFX
    PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
        JUCE_REPORT_APP_USAGE=0
)

# Link JUCE modules
target_link_libraries(DrippyFX
    PRIVATE
        juce::juce_audio_utils
        juce::juce_dsp
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags
)

# Additional compiler flags for optimization
if(MSVC)
    target_compile_options(DrippyFX PRIVATE /W4 /fp:fast /arch:AVX2)
else()
    target_compile_options(DrippyFX PRIVATE -Wall -Wextra -Wpedantic)
endif()

juce_add_plugin(CorvusInstrument
    COMPANY_NAME "Corvus Audio"
    BUNDLE_ID "com.corvusaudio.CorvusInstrument"
    IS_SYNTH TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD ${CORVUS_COPY_PLUGIN_AFTER_BUILD}
    PLUGIN_MANUFACTURER_CODE Crvs
    PLUGIN_CODE Cvi1
    FORMATS VST3 Standalone
    PRODUCT_NAME "Corvus Instrument"
    VST3_CATEGORIES "Instrument" "Synth"
)

juce_generate_juce_header(CorvusInstrument)

target_sources(CorvusInstrument
    PRIVATE
        instrument/CorvusInstrumentEditor.cpp
        instrument/CorvusInstrumentProcessor.cpp
)

target_compile_definitions(CorvusInstrument
    PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
        JUCE_REPORT_APP_USAGE=0
)

target_link_libraries(CorvusInstrument
    PRIVATE
        juce::juce_audio_utils
        juce::juce_dsp
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags
)

if(MSVC)
    target_compile_options(CorvusInstrument PRIVATE /W4 /fp:fast /arch:AVX2)
else()
    target_compile_options(CorvusInstrument PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Deterministic DSP regression harness. This is a separate console target so
# the existing FX plug-in identity and build products remain untouched.
juce_add_console_app(CorvusDSPTests
    PRODUCT_NAME "Corvus DSP Tests"
)

juce_generate_juce_header(CorvusDSPTests)

target_sources(CorvusDSPTests
    PRIVATE
        instrument/CorvusInstrumentEditor.cpp
        instrument/CorvusInstrumentProcessor.cpp
        tests/CorvusDspTests.cpp
)

target_include_directories(CorvusDSPTests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

target_compile_definitions(CorvusDSPTests
    PRIVATE
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
        JUCE_REPORT_APP_USAGE=0
)

target_link_libraries(CorvusDSPTests
    PRIVATE
        juce::juce_audio_utils
        juce::juce_dsp
        juce::juce_recommended_config_flags
        juce::juce_recommended_warning_flags
)

if(MSVC)
    target_compile_options(CorvusDSPTests PRIVATE /W4 /fp:fast /arch:AVX2)
else()
    target_compile_options(CorvusDSPTests PRIVATE -Wall -Wextra -Wpedantic)
endif()


# Convenience helper for the regression harness.
add_custom_target(CorvusDSPTestsRun
    COMMAND $<TARGET_FILE:CorvusDSPTests>
    DEPENDS CorvusDSPTests
)

# Session regressions exercise the real FX processor independently of the
# instrument's createPluginFilter entry point and DSP fixture.
juce_add_console_app(CorvusFXStateTests PRODUCT_NAME "Corvus FX State Tests")
juce_generate_juce_header(CorvusFXStateTests)
target_sources(CorvusFXStateTests PRIVATE
    PluginProcessor.cpp
    PluginEditor.cpp
    tests/CorvusFxStateTests.cpp
)
target_include_directories(CorvusFXStateTests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(CorvusFXStateTests PRIVATE
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
)
target_link_libraries(CorvusFXStateTests PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)
add_custom_target(CorvusFXStateTestsRun
    COMMAND $<TARGET_FILE:CorvusFXStateTests>
    DEPENDS CorvusFXStateTests
)

# ── CV-033: offline demo renderers ───────────────────────────────────────────
# Two console targets, one per product. Each links the real product processor
# (including its createPluginFilter factory) and the same shared main. Keeping
# the products in separate executables avoids duplicate createPluginFilter
# symbols; nothing is copied into a synthetic DSP stand-in. The renderers use
# no audio device, host, microphone, user input file, network or model.
juce_add_console_app(CorvusRenderFX
    PRODUCT_NAME "CorvusRenderFX"
)

juce_generate_juce_header(CorvusRenderFX)

target_sources(CorvusRenderFX
    PRIVATE
        PluginProcessor.cpp
        PluginEditor.cpp
        tools/CorvusOfflineRender.cpp
)

target_include_directories(CorvusRenderFX
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

target_compile_definitions(CorvusRenderFX
    PRIVATE
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        CORVUS_RENDER_PRODUCT_FX=1
)

target_link_libraries(CorvusRenderFX
    PRIVATE
        juce::juce_audio_utils
        juce::juce_dsp
        juce::juce_recommended_config_flags
        juce::juce_recommended_warning_flags
)

if(MSVC)
    target_compile_options(CorvusRenderFX PRIVATE /W4 /fp:fast /arch:AVX2)
else()
    target_compile_options(CorvusRenderFX PRIVATE -Wall -Wextra -Wpedantic)
endif()

juce_add_console_app(CorvusRenderInstrument
    PRODUCT_NAME "CorvusRenderInstrument"
)

juce_generate_juce_header(CorvusRenderInstrument)

target_sources(CorvusRenderInstrument
    PRIVATE
        instrument/CorvusInstrumentProcessor.cpp
        instrument/CorvusInstrumentEditor.cpp
        tools/CorvusOfflineRender.cpp
)

target_include_directories(CorvusRenderInstrument
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

target_compile_definitions(CorvusRenderInstrument
    PRIVATE
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        CORVUS_RENDER_PRODUCT_INSTRUMENT=1
)

target_link_libraries(CorvusRenderInstrument
    PRIVATE
        juce::juce_audio_utils
        juce::juce_dsp
        juce::juce_recommended_config_flags
        juce::juce_recommended_warning_flags
)

if(MSVC)
    target_compile_options(CorvusRenderInstrument PRIVATE /W4 /fp:fast /arch:AVX2)
else()
    target_compile_options(CorvusRenderInstrument PRIVATE -Wall -Wextra -Wpedantic)
endif()
