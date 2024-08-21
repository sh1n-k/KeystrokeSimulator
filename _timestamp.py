from datetime import datetime, timezone, timedelta


def timestamp_to_ktc(timestamp):
    utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    ktc_time = utc_time + timedelta(hours=9)
    return ktc_time.strftime("%Y-%m-%d %H:%M:%S")


# Example usage
timestamp = 1724238195  # Example Unix timestamp
print(timestamp_to_ktc(timestamp))
