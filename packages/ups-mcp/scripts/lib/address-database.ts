/**
 * Pre-Validated US Address Database
 *
 * Contains ~100 real US addresses that pass UPS address validation.
 * Addresses are weighted by state distribution for predictable test scenarios.
 *
 * Distribution:
 * - CA: 25%
 * - NY: 15%
 * - TX: 15%
 * - FL: 15%
 * - Other states: 30% combined
 */

import type { ValidatedAddress, USStateCode, StateDistribution } from "./types.js";

/**
 * State distribution for test coverage
 */
export const STATE_DISTRIBUTION: StateDistribution[] = [
  { state: "CA", weight: 0.25 },
  { state: "NY", weight: 0.15 },
  { state: "TX", weight: 0.15 },
  { state: "FL", weight: 0.15 },
  { state: "IL", weight: 0.05 },
  { state: "PA", weight: 0.05 },
  { state: "OH", weight: 0.04 },
  { state: "GA", weight: 0.04 },
  { state: "NC", weight: 0.03 },
  { state: "WA", weight: 0.03 },
  { state: "MA", weight: 0.03 },
  { state: "CO", weight: 0.03 },
];

/**
 * Pre-validated US addresses organized by state
 * These are real addresses that pass UPS validation
 */
export const ADDRESSES_BY_STATE: Record<USStateCode, ValidatedAddress[]> = {
  // California (25%) - 25 addresses
  CA: [
    { address1: "1600 Amphitheatre Parkway", city: "Mountain View", state: "CA", zip: "94043", landmark: "Google HQ" },
    { address1: "1 Apple Park Way", city: "Cupertino", state: "CA", zip: "95014", landmark: "Apple HQ" },
    { address1: "1 Hacker Way", city: "Menlo Park", state: "CA", zip: "94025", landmark: "Meta HQ" },
    { address1: "500 Terry A Francois Blvd", city: "San Francisco", state: "CA", zip: "94158", landmark: "Chase Center" },
    { address1: "350 5th Ave", city: "San Diego", state: "CA", zip: "92101", landmark: "Horton Plaza" },
    { address1: "6922 Hollywood Blvd", city: "Los Angeles", state: "CA", zip: "90028", landmark: "Hollywood Walk of Fame" },
    { address1: "1111 S Figueroa St", city: "Los Angeles", state: "CA", zip: "90015", landmark: "Crypto Arena" },
    { address1: "100 Universal City Plaza", city: "Universal City", state: "CA", zip: "91608", landmark: "Universal Studios" },
    { address1: "1313 Disneyland Dr", city: "Anaheim", state: "CA", zip: "92802", landmark: "Disneyland" },
    { address1: "2175 N California Blvd", city: "Walnut Creek", state: "CA", zip: "94596", landmark: "Broadway Plaza" },
    { address1: "333 Post St", city: "San Francisco", state: "CA", zip: "94108", landmark: "Union Square" },
    { address1: "845 Market St", city: "San Francisco", state: "CA", zip: "94103", landmark: "Westfield SF Centre" },
    { address1: "1 Warriors Way", city: "San Francisco", state: "CA", zip: "94158", landmark: "Chase Center Arena" },
    { address1: "100 Cyril Magnin St", city: "San Francisco", state: "CA", zip: "94102", landmark: "Hotel Nikko" },
    { address1: "3251 20th Ave", city: "San Francisco", state: "CA", zip: "94132", landmark: "Stonestown Galleria" },
    { address1: "10250 Santa Monica Blvd", city: "Los Angeles", state: "CA", zip: "90067", landmark: "Westfield Century City" },
    { address1: "189 The Grove Dr", city: "Los Angeles", state: "CA", zip: "90036", landmark: "The Grove" },
    { address1: "7007 Friars Rd", city: "San Diego", state: "CA", zip: "92108", landmark: "Fashion Valley Mall" },
    { address1: "4545 La Jolla Village Dr", city: "San Diego", state: "CA", zip: "92122", landmark: "Westfield UTC" },
    { address1: "2855 Stevens Creek Blvd", city: "Santa Clara", state: "CA", zip: "95050", landmark: "Valley Fair Mall" },
    { address1: "865 Market St", city: "San Francisco", state: "CA", zip: "94103", landmark: "Westfield San Francisco" },
    { address1: "3333 Bristol St", city: "Costa Mesa", state: "CA", zip: "92626", landmark: "South Coast Plaza" },
    { address1: "1 Snoopy Pl", city: "Santa Rosa", state: "CA", zip: "95403", landmark: "Charles Schulz Museum" },
    { address1: "1 Infinite Loop", city: "Cupertino", state: "CA", zip: "95014", landmark: "Apple Campus" },
    { address1: "24600 Clawiter Rd", city: "Hayward", state: "CA", zip: "94545", landmark: "Amazon Fulfillment" },
  ],

  // New York (15%) - 15 addresses
  NY: [
    { address1: "350 5th Ave", city: "New York", state: "NY", zip: "10118", landmark: "Empire State Building" },
    { address1: "20 W 34th St", city: "New York", state: "NY", zip: "10001", landmark: "Macy's Herald Square" },
    { address1: "1 Rockefeller Plaza", city: "New York", state: "NY", zip: "10020", landmark: "Rockefeller Center" },
    { address1: "1 World Trade Center", city: "New York", state: "NY", zip: "10007", landmark: "One WTC" },
    { address1: "4 Pennsylvania Plaza", city: "New York", state: "NY", zip: "10001", landmark: "Madison Square Garden" },
    { address1: "767 5th Ave", city: "New York", state: "NY", zip: "10153", landmark: "Trump Tower" },
    { address1: "151 W 34th St", city: "New York", state: "NY", zip: "10001", landmark: "Macy's" },
    { address1: "1000 5th Ave", city: "New York", state: "NY", zip: "10028", landmark: "Metropolitan Museum" },
    { address1: "200 Central Park West", city: "New York", state: "NY", zip: "10024", landmark: "Natural History Museum" },
    { address1: "11 W 53rd St", city: "New York", state: "NY", zip: "10019", landmark: "MoMA" },
    { address1: "1 E 161st St", city: "Bronx", state: "NY", zip: "10451", landmark: "Yankee Stadium" },
    { address1: "620 Atlantic Ave", city: "Brooklyn", state: "NY", zip: "11217", landmark: "Barclays Center" },
    { address1: "136-20 38th Ave", city: "Flushing", state: "NY", zip: "11354", landmark: "New World Mall" },
    { address1: "500 Crossgates Mall Rd", city: "Albany", state: "NY", zip: "12203", landmark: "Crossgates Mall" },
    { address1: "1 Galleria Dr", city: "Buffalo", state: "NY", zip: "14225", landmark: "Walden Galleria" },
  ],

  // Texas (15%) - 15 addresses
  TX: [
    { address1: "2501 N Harwood St", city: "Dallas", state: "TX", zip: "75201", landmark: "Perot Museum" },
    { address1: "100 E Riverside Dr", city: "Austin", state: "TX", zip: "78704", landmark: "Austin City Limits" },
    { address1: "1 AT&T Way", city: "Arlington", state: "TX", zip: "76011", landmark: "AT&T Stadium" },
    { address1: "1001 Avenida De Las Americas", city: "Houston", state: "TX", zip: "77010", landmark: "Minute Maid Park" },
    { address1: "8687 N Central Expy", city: "Dallas", state: "TX", zip: "75225", landmark: "NorthPark Center" },
    { address1: "2601 Preston Rd", city: "Frisco", state: "TX", zip: "75034", landmark: "Stonebriar Centre" },
    { address1: "5015 Westheimer Rd", city: "Houston", state: "TX", zip: "77056", landmark: "The Galleria" },
    { address1: "301 Alamo Plaza", city: "San Antonio", state: "TX", zip: "78205", landmark: "The Alamo" },
    { address1: "15900 La Cantera Pkwy", city: "San Antonio", state: "TX", zip: "78256", landmark: "The Shops at La Cantera" },
    { address1: "4200 Main St", city: "Houston", state: "TX", zip: "77002", landmark: "Houston Museum District" },
    { address1: "1800 N Shoreline Blvd", city: "Corpus Christi", state: "TX", zip: "78401", landmark: "Texas State Aquarium" },
    { address1: "2717 N Loop 250 W", city: "Midland", state: "TX", zip: "79707", landmark: "Midland Park Mall" },
    { address1: "8505 Gateway Blvd W", city: "El Paso", state: "TX", zip: "79925", landmark: "Bassett Place" },
    { address1: "6121 W Park Blvd", city: "Plano", state: "TX", zip: "75093", landmark: "The Shops at Legacy" },
    { address1: "11111 Katy Fwy", city: "Houston", state: "TX", zip: "77079", landmark: "Memorial City Mall" },
  ],

  // Florida (15%) - 15 addresses
  FL: [
    { address1: "1180 Seven Seas Dr", city: "Orlando", state: "FL", zip: "32830", landmark: "Magic Kingdom" },
    { address1: "1000 Universal Studios Plaza", city: "Orlando", state: "FL", zip: "32819", landmark: "Universal Orlando" },
    { address1: "8001 S Orange Blossom Trl", city: "Orlando", state: "FL", zip: "32809", landmark: "Mall at Millenia" },
    { address1: "601 E Kennedy Blvd", city: "Tampa", state: "FL", zip: "33602", landmark: "Amalie Arena" },
    { address1: "3401 Bayshore Blvd", city: "Tampa", state: "FL", zip: "33629", landmark: "Tampa Bay Waterfront" },
    { address1: "1601 Biscayne Blvd", city: "Miami", state: "FL", zip: "33132", landmark: "Adrienne Arsht Center" },
    { address1: "1111 Lincoln Rd", city: "Miami Beach", state: "FL", zip: "33139", landmark: "Lincoln Road Mall" },
    { address1: "19501 Biscayne Blvd", city: "Aventura", state: "FL", zip: "33180", landmark: "Aventura Mall" },
    { address1: "9501 International Dr", city: "Orlando", state: "FL", zip: "32819", landmark: "Orlando Premium Outlets" },
    { address1: "6000 Universal Blvd", city: "Orlando", state: "FL", zip: "32819", landmark: "Universal CityWalk" },
    { address1: "8000 W Broward Blvd", city: "Plantation", state: "FL", zip: "33388", landmark: "Westfield Broward" },
    { address1: "9469 W Atlantic Blvd", city: "Coral Springs", state: "FL", zip: "33071", landmark: "Coral Square" },
    { address1: "5530 W Copans Rd", city: "Margate", state: "FL", zip: "33063", landmark: "Coral Ridge Mall" },
    { address1: "801 Silks Run", city: "Hallandale Beach", state: "FL", zip: "33009", landmark: "Gulfstream Park" },
    { address1: "2700 N Military Trl", city: "West Palm Beach", state: "FL", zip: "33409", landmark: "Palm Beach Outlets" },
  ],

  // Illinois (5%) - 5 addresses
  IL: [
    { address1: "233 S Wacker Dr", city: "Chicago", state: "IL", zip: "60606", landmark: "Willis Tower" },
    { address1: "875 N Michigan Ave", city: "Chicago", state: "IL", zip: "60611", landmark: "John Hancock Center" },
    { address1: "111 S State St", city: "Chicago", state: "IL", zip: "60603", landmark: "Macy's State Street" },
    { address1: "1901 N Clybourn Ave", city: "Chicago", state: "IL", zip: "60614", landmark: "Lincoln Park" },
    { address1: "520 N Michigan Ave", city: "Chicago", state: "IL", zip: "60611", landmark: "Magnificent Mile" },
  ],

  // Pennsylvania (5%) - 5 addresses
  PA: [
    { address1: "1 N Broad St", city: "Philadelphia", state: "PA", zip: "19107", landmark: "City Hall" },
    { address1: "3601 S Broad St", city: "Philadelphia", state: "PA", zip: "19148", landmark: "Wells Fargo Center" },
    { address1: "1500 Market St", city: "Philadelphia", state: "PA", zip: "19102", landmark: "Centre Square" },
    { address1: "1000 Ross Park Mall Dr", city: "Pittsburgh", state: "PA", zip: "15237", landmark: "Ross Park Mall" },
    { address1: "100 Robinson Centre Dr", city: "Pittsburgh", state: "PA", zip: "15205", landmark: "Robinson Town Centre" },
  ],

  // Ohio (4%) - 4 addresses
  OH: [
    { address1: "1 Rock and Roll Hall of Fame Plaza", city: "Cleveland", state: "OH", zip: "44114", landmark: "Rock Hall" },
    { address1: "1 Nationwide Blvd", city: "Columbus", state: "OH", zip: "43215", landmark: "Nationwide Arena" },
    { address1: "7500 Mentor Ave", city: "Mentor", state: "OH", zip: "44060", landmark: "Great Lakes Mall" },
    { address1: "7875 Montgomery Rd", city: "Cincinnati", state: "OH", zip: "45236", landmark: "Kenwood Towne Centre" },
  ],

  // Georgia (4%) - 4 addresses
  GA: [
    { address1: "3393 Peachtree Rd NE", city: "Atlanta", state: "GA", zip: "30326", landmark: "Lenox Square" },
    { address1: "1 CNN Center", city: "Atlanta", state: "GA", zip: "30303", landmark: "CNN Center" },
    { address1: "225 Baker St NW", city: "Atlanta", state: "GA", zip: "30313", landmark: "World of Coca-Cola" },
    { address1: "1 AMB Dr NW", city: "Atlanta", state: "GA", zip: "30313", landmark: "Mercedes-Benz Stadium" },
  ],

  // North Carolina (3%) - 3 addresses
  NC: [
    { address1: "333 E Trade St", city: "Charlotte", state: "NC", zip: "28202", landmark: "Spectrum Center" },
    { address1: "4400 Sharon Rd", city: "Charlotte", state: "NC", zip: "28211", landmark: "SouthPark Mall" },
    { address1: "8111 Concord Mills Blvd", city: "Concord", state: "NC", zip: "28027", landmark: "Concord Mills" },
  ],

  // Washington (3%) - 3 addresses
  WA: [
    { address1: "400 Pine St", city: "Seattle", state: "WA", zip: "98101", landmark: "Westlake Center" },
    { address1: "2601 Elliott Ave", city: "Seattle", state: "WA", zip: "98121", landmark: "Pier 66" },
    { address1: "4502 S Steele St", city: "Tacoma", state: "WA", zip: "98409", landmark: "Tacoma Mall" },
  ],

  // Massachusetts (3%) - 3 addresses
  MA: [
    { address1: "800 Boylston St", city: "Boston", state: "MA", zip: "02199", landmark: "Prudential Center" },
    { address1: "100 Huntington Ave", city: "Boston", state: "MA", zip: "02116", landmark: "Copley Place" },
    { address1: "75 Middlesex Tpke", city: "Burlington", state: "MA", zip: "01803", landmark: "Burlington Mall" },
  ],

  // Colorado (3%) - 3 addresses
  CO: [
    { address1: "1701 Bryant St", city: "Denver", state: "CO", zip: "80204", landmark: "Mile High Stadium" },
    { address1: "3000 E 1st Ave", city: "Denver", state: "CO", zip: "80206", landmark: "Cherry Creek Mall" },
    { address1: "14200 E Alameda Ave", city: "Aurora", state: "CO", zip: "80012", landmark: "Town Center at Aurora" },
  ],

  // Remaining states with minimal coverage
  MI: [{ address1: "2800 W Big Beaver Rd", city: "Troy", state: "MI", zip: "48084", landmark: "Somerset Collection" }],
  NJ: [{ address1: "1 American Dream Way", city: "East Rutherford", state: "NJ", zip: "07073", landmark: "American Dream" }],
  VA: [{ address1: "8100 Tysons Corner Center", city: "McLean", state: "VA", zip: "22102", landmark: "Tysons Corner" }],
  AZ: [{ address1: "7014 E Camelback Rd", city: "Scottsdale", state: "AZ", zip: "85251", landmark: "Scottsdale Fashion Square" }],
  TN: [{ address1: "2615 West End Ave", city: "Nashville", state: "TN", zip: "37203", landmark: "The Mall at Green Hills" }],
  IN: [{ address1: "8702 Keystone Crossing", city: "Indianapolis", state: "IN", zip: "46240", landmark: "Fashion Mall" }],
  MO: [{ address1: "1801 St Louis Galleria", city: "St Louis", state: "MO", zip: "63117", landmark: "Saint Louis Galleria" }],
  MD: [{ address1: "7101 Democracy Blvd", city: "Bethesda", state: "MD", zip: "20817", landmark: "Westfield Montgomery" }],
  WI: [{ address1: "2500 N Mayfair Rd", city: "Wauwatosa", state: "WI", zip: "53226", landmark: "Mayfair Mall" }],
  MN: [{ address1: "60 E Broadway", city: "Bloomington", state: "MN", zip: "55425", landmark: "Mall of America" }],
  SC: [{ address1: "385 Columbiana Dr", city: "Columbia", state: "SC", zip: "29212", landmark: "Columbiana Centre" }],
  AL: [{ address1: "2000 Riverchase Galleria", city: "Hoover", state: "AL", zip: "35244", landmark: "Riverchase Galleria" }],
  LA: [{ address1: "1500 Poydras St", city: "New Orleans", state: "LA", zip: "70112", landmark: "Smoothie King Center" }],
  KY: [{ address1: "7900 Shelbyville Rd", city: "Louisville", state: "KY", zip: "40222", landmark: "Oxmoor Center" }],
  OR: [{ address1: "701 SW 6th Ave", city: "Portland", state: "OR", zip: "97204", landmark: "Pioneer Courthouse Square" }],
  OK: [{ address1: "1901 Northwest Expy", city: "Oklahoma City", state: "OK", zip: "73118", landmark: "Penn Square Mall" }],
  CT: [{ address1: "500 Westfarms Mall", city: "Farmington", state: "CT", zip: "06032", landmark: "Westfarms Mall" }],
  UT: [{ address1: "50 S Main St", city: "Salt Lake City", state: "UT", zip: "84101", landmark: "City Creek Center" }],
  NV: [{ address1: "3500 Las Vegas Blvd S", city: "Las Vegas", state: "NV", zip: "89109", landmark: "The Venetian" }],
  AR: [{ address1: "2855 Lakewood Village Dr", city: "North Little Rock", state: "AR", zip: "72116", landmark: "Lakewood Village" }],
  MS: [{ address1: "1200 E County Line Rd", city: "Ridgeland", state: "MS", zip: "39157", landmark: "Northpark Mall" }],
  KS: [{ address1: "10600 Quivira Rd", city: "Overland Park", state: "KS", zip: "66215", landmark: "Oak Park Mall" }],
  NM: [{ address1: "6600 Menaul Blvd NE", city: "Albuquerque", state: "NM", zip: "87110", landmark: "Coronado Center" }],
  NE: [{ address1: "10000 California St", city: "Omaha", state: "NE", zip: "68114", landmark: "Westroads Mall" }],
  ID: [{ address1: "350 N Milwaukee St", city: "Boise", state: "ID", zip: "83704", landmark: "Boise Towne Square" }],
  WV: [{ address1: "6000 Grand Central Mall", city: "Parkersburg", state: "WV", zip: "26101", landmark: "Grand Central Mall" }],
  HI: [{ address1: "2201 Kalakaua Ave", city: "Honolulu", state: "HI", zip: "96815", landmark: "Waikiki Shopping Plaza" }],
  NH: [{ address1: "310 Daniel Webster Hwy", city: "Nashua", state: "NH", zip: "03060", landmark: "Pheasant Lane Mall" }],
  ME: [{ address1: "364 Maine Mall Rd", city: "South Portland", state: "ME", zip: "04106", landmark: "Maine Mall" }],
  MT: [{ address1: "2525 N 7th Ave", city: "Bozeman", state: "MT", zip: "59715", landmark: "Gallatin Valley Mall" }],
  RI: [{ address1: "99 Providence Place", city: "Providence", state: "RI", zip: "02903", landmark: "Providence Place" }],
  DE: [{ address1: "132 Christiana Mall", city: "Newark", state: "DE", zip: "19702", landmark: "Christiana Mall" }],
  SD: [{ address1: "4001 W 41st St", city: "Sioux Falls", state: "SD", zip: "57106", landmark: "Empire Mall" }],
  ND: [{ address1: "2800 South Columbia Rd", city: "Grand Forks", state: "ND", zip: "58201", landmark: "Columbia Mall" }],
  AK: [{ address1: "320 W 5th Ave", city: "Anchorage", state: "AK", zip: "99501", landmark: "5th Avenue Mall" }],
  VT: [{ address1: "100 Dorset St", city: "South Burlington", state: "VT", zip: "05403", landmark: "University Mall" }],
  DC: [{ address1: "1600 Pennsylvania Avenue NW", city: "Washington", state: "DC", zip: "20500", landmark: "White House" }],
  WY: [{ address1: "1400 Dell Range Blvd", city: "Cheyenne", state: "WY", zip: "82009", landmark: "Frontier Mall" }],
};

/**
 * Flattened list of all addresses for random selection
 */
export const ALL_ADDRESSES: ValidatedAddress[] = Object.values(ADDRESSES_BY_STATE).flat();

/**
 * Gets a random address weighted by state distribution
 *
 * @param random - Random number generator (0-1)
 * @returns Selected address
 */
export function getWeightedRandomAddress(random: () => number): ValidatedAddress {
  // Select state based on weight distribution
  const stateRoll = random();
  let cumulative = 0;
  let selectedState: USStateCode = "CA";

  for (const { state, weight } of STATE_DISTRIBUTION) {
    cumulative += weight;
    if (stateRoll < cumulative) {
      selectedState = state;
      break;
    }
  }

  // Select random address from state
  const addresses = ADDRESSES_BY_STATE[selectedState];
  const index = Math.floor(random() * addresses.length);
  return addresses[index];
}

/**
 * Gets an address by state (for targeted testing)
 *
 * @param state - US state code
 * @param index - Address index within state
 * @returns Selected address or undefined
 */
export function getAddressByState(state: USStateCode, index: number): ValidatedAddress | undefined {
  const addresses = ADDRESSES_BY_STATE[state];
  if (!addresses || addresses.length === 0) {
    return undefined;
  }
  return addresses[index % addresses.length];
}

/**
 * Full US state names for address formatting
 */
export const US_STATE_NAMES: Record<USStateCode, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
  IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
  ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon",
  PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
  TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia",
  WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};
