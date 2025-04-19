from faker import Faker
import json

fake = Faker("en_US")
profile = {
    # Personal
    "first_name":fake.first_name(),
    "last_name":fake.last_name(),
    "gender": fake.random_element(["Male", "Female"]),
    "birthdate": fake.date_of_birth(minimum_age=18, maximum_age=30).isoformat(),
    "ssn": fake.ssn(),
    "phone": fake.phone_number(),

    # Address
    "street": fake.street_address(),
    "city": fake.city(),
    "state": fake.state(),
    "zip": fake.zipcode(),

}
print(profile)

with open("profile.json", "w") as f:
    json.dump(profile, f)