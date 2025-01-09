from typing import TypedDict, Literal

class ScheduleEntry(TypedDict):
    """Represents a single entry in the light schedule.
    
    Attributes:
        time (str): The time of day for this schedule entry in 24-hour format (HH:MM)
        warmBrightness (int): The brightness level for warm light (0-100)
        coolBrightness (int): The brightness level for cool light (0-100)
        unix_time (int): The Unix timestamp for this schedule entry
    """
    time: str
    warmBrightness: int
    coolBrightness: int
    unix_time: int

class ScheduleData(TypedDict):
    """Represents the complete light schedule data structure.
    
    Attributes:
        mode (Literal['dayNight', 'scheduled', 'demo']): The current operating mode for the lights
            - 'dayNight': Automatically adjusts based on time of day
            - 'scheduled': Follows the user-defined schedule
            - 'demo': Runs a demonstration cycle
        schedule (List[ScheduleEntry]): Array of schedule entries that define the light settings
        sunrise (ScheduleEntry): The sunrise schedule entry
        sunset (ScheduleEntry): The sunset schedule entry
        natural_sunset (ScheduleEntry): The natural sunset schedule entry
        civil_twilight_begin (ScheduleEntry): The civil twilight begin schedule entry
        civil_twilight_end (ScheduleEntry): The civil twilight end schedule entry
        natural_twilight_end (ScheduleEntry): The natural twilight end schedule entry
        bed_time (ScheduleEntry): The bed time schedule entry
        night_time (ScheduleEntry): The night time schedule entry
        update_time (str): The time of day to update the schedule (HH:MM format)
        update_time_unix (int): Unix timestamp for the next schedule update
    """
    mode: Literal['dayNight', 'scheduled', 'demo']
    schedule: list[ScheduleEntry]
    sunrise: ScheduleEntry
    sunset: ScheduleEntry
    natural_sunset: ScheduleEntry
    civil_twilight_begin: ScheduleEntry
    civil_twilight_end: ScheduleEntry
    natural_twilight_end: ScheduleEntry
    bed_time: ScheduleEntry
    night_time: ScheduleEntry
    update_time: str
    update_time_unix: int
