"""
Data model for TaxonGPT.

Defines the core biological entities:
- Character
- Condition
- Taxon
- Dataset

These classes are intentionally lightweight and contain no business logic.
They serve as the shared data structure across parsing, KG, and reasoning layers.
"""


class Character:
    """
    Represents a character with discrete states used in the dataset.

    Attributes:
        index (int): Character index in dataset
        name (str): Character name/description
        states (dict): {state_id: state_label}
        char_type (str): Type of character (default: "discrete")
        condition (Condition | None): Optional dependency on another character
    """

    def __init__(self, index, name, states, char_type="discrete"):
        self.index = index
        self.name = name
        self.states = states  # dict: {state_id: state_label}
        self.char_type = char_type
        self.condition = None  # optional Condition object
    
    def get_display_name(self):
        """
        Return a human-readable character name.
        Supports hierarchical names stored as lists.
        """
        if isinstance(self.name, list):
            return ", ".join(self.name)
        return self.name

    def __repr__(self):
        return f"Character(index={self.index}, name='{self.get_display_name()}')"


class Condition:
    """
    Represents a dependency of one character on another.

    Example:
        Character B is only applicable if Character A is in a given state.
    """

    def __init__(self, depends_on_char, required_states):
        self.depends_on_char = depends_on_char
        self.required_states = required_states

    def __repr__(self):
        return f"Condition(depends_on={self.depends_on_char}, states={self.required_states})"


class Taxon:
    """
    Represents a taxon and its associated character states.

    Attributes:
        name (str): Taxon name
        states (dict): {character_index: state_value}
    """

    def __init__(self, name):
        self.name = name
        self.states = {}

    def __repr__(self):
        return f"Taxon(name='{self.name}')"


class Dataset:
    """
    Container for all taxa, characters, and optional metadata.

    Attributes:
        characters (list[Character])
        taxa (list[Taxon])
        character_groups (dict): Optional grouping of characters
    """

    def __init__(self):
        self.characters = []
        self.taxa = []
        self.character_groups = {}

        