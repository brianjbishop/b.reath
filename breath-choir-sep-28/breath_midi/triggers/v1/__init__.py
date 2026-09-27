from breath_midi.triggers.v1.consistent_breaths import ConsistentBreathsTrigger
from breath_midi.triggers.v1.exhale_onset import ExhaleOnsetTrigger
from breath_midi.triggers.v1.inhale_onset import InhaleOnsetTrigger
from breath_midi.triggers.v1.sustain_cc import ExhaleSustainCcTrigger, InhaleSustainCcTrigger


def v1_strategies():
    return [
        InhaleOnsetTrigger(),
        ExhaleOnsetTrigger(),
        InhaleSustainCcTrigger(),
        ExhaleSustainCcTrigger(),
        ConsistentBreathsTrigger(),
    ]

