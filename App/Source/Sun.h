#pragma once


class Sun: public Astro{
public:
    // Constructors and destructors.
    Sun(AudioContainer&, Parameters&, ControlPanel&);
    ~Sun() override;

public:
    // View methods.
    void paint(Graphics& g) override;
    void resized() override;

    void draw() override;
    void draw(int, int, int) override;

public:
    // Interface methods.
    juce::ValueTree getState() override;

private:
    // Controller methods.
    bool hitTest(int, int) override;
    void mouseDown(const MouseEvent& e) override;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(Sun)
};
