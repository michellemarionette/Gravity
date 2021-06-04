#pragma once


class Planet: public juce::Component{
public:
    // Value used to activate planet destruction.
    juce::Value m_Destroy;  

    // Value used to activate lerp graph calculation.
    juce::Value m_LerpGraph;

    // Generated latents.
    at::Tensor m_Latents;
    at::Tensor m_LerpLatents;

private:
    juce::ComponentDragger m_Dragger;

    // Map boundaries.
    int m_MapWidth;
    int m_MapHeight;

    // Collision safety.
    int m_PosX;
    int m_PosY;

protected:
    // Pointer to array containing planets.
    juce::OwnedArray<Planet>* m_PlanetsPtr;

    // Used to access the generator instantiated in
    // the PluginProcessor.
    AudioContainer* m_AudioContainerPtr;
    Parameters* m_ParametersPtr;

    // Generated sample.
    juce::Array<float> m_Sample;

public:
    Planet();
    Planet(juce::OwnedArray<Planet>*, AudioContainer*, Parameters*);
    ~Planet() override;

    void paint(Graphics&) override;
    void resized() override;
    
    // When called the component is redrawn.
    void draw(int, int, int);

    // When called the planet will be resized.
    // X and Y are calculated such that the planet will remain centred.
    void resizePlanet(int);

    void setDiameter(int);
    
    // Sets the map boundaries.
    void setMapBoundaries(int, int);
    void setPosXY(int, int);

    virtual int getDiameter();
    int getClipBoundary();
    float getDistance(int, int, int, int);
    float getDistance(Planet*, Planet*);

    // Returns the the centre X position of the planet,
    // taking into a account clip boundary.
    int getCentreX(Planet*);

    // Returns the the centre Y position of the planet,
    // taking into a account clip boundary.
    int getCentreY(Planet*);

    virtual void generateLatents();
    virtual void generateSample(at::Tensor&);

    void updateGraph();

    // Changes states in AudioContainer.
    void addSample();

    // Plays sample.
    void playSample();

private:
    bool hitTest(int, int) override;
    void mouseDown(const MouseEvent&) override;
    void mouseUp(const MouseEvent&) override;
    void mouseDrag(const MouseEvent&) override;

    // If the mouse wheel is moved the diameter of the planet is
    // modified making sure it is not going over the size limitations.
    void mouseWheelMove(const MouseEvent&, const MouseWheelDetails&) override;
    void visibilityChanged() override;

    void checkCollision();
    void checkBounds();

    // Allocates storage to array that holds sample.
    void allocateStorage();

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(Planet)
};
