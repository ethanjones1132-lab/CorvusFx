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

# Plugin configuration
juce_add_plugin(DrippyFX
    COMPANY_NAME "DrippyFX"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD TRUE
    PLUGIN_MANUFACTURER_CODE Drip
    PLUGIN_CODE Dfx1
    FORMATS VST3 AU Standalone
    PRODUCT_NAME "DrippyFX"
    VST3_CATEGORIES "Fx" "Dynamics" "Modulation" "Reverb" "Delay"
)

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
