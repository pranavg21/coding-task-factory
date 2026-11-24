// Feature tests for Json::Value::flatten. Built as a separate test program
// that reuses jsoncpp's own test framework (jsontest).
#include "jsontest.h"
#include <json/json.h>

static std::deque<JsonTest::TestCaseFactory> local_;
#define JSONTEST_FIXTURE_LOCAL(FixtureType, name)                              \
  JSONTEST_FIXTURE_V2(FixtureType, name, local_)

struct FlattenTest : JsonTest::TestCase {
  static Json::Value parse(const char* text) {
    Json::Value root;
    Json::CharReaderBuilder builder;
    std::string errors;
    std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    std::string doc(text);
    reader->parse(doc.data(), doc.data() + doc.size(), &root, &errors);
    return root;
  }
};

JSONTEST_FIXTURE_LOCAL(FlattenTest, nestedObjectsAndArrays) {
  Json::Value flat = parse(R"({"a":{"b":[1,2]},"c":"x"})").flatten();
  JSONTEST_ASSERT(flat.isObject());
  JSONTEST_ASSERT_EQUAL(3u, flat.size());
  JSONTEST_ASSERT_EQUAL(1, flat["a.b.0"].asInt());
  JSONTEST_ASSERT_EQUAL(2, flat["a.b.1"].asInt());
  JSONTEST_ASSERT_STRING_EQUAL("x", flat["c"].asString());
}

JSONTEST_FIXTURE_LOCAL(FlattenTest, customSeparator) {
  Json::Value flat = parse(R"({"server":{"port":8080}})").flatten('/');
  JSONTEST_ASSERT(flat.isMember("server/port"));
  JSONTEST_ASSERT(!flat.isMember("server.port"));
  JSONTEST_ASSERT_EQUAL(8080, flat["server/port"].asInt());
}

JSONTEST_FIXTURE_LOCAL(FlattenTest, emptyContainersAreLeaves) {
  Json::Value flat = parse(R"({"tags":[],"meta":{},"n":null})").flatten();
  JSONTEST_ASSERT_EQUAL(3u, flat.size());
  JSONTEST_ASSERT(flat["tags"].isArray() && flat["tags"].empty());
  JSONTEST_ASSERT(flat["meta"].isObject() && flat["meta"].empty());
  JSONTEST_ASSERT(flat["n"].isNull());
}

JSONTEST_FIXTURE_LOCAL(FlattenTest, scalarRootUsesEmptyKey) {
  Json::Value flat = Json::Value(42).flatten();
  JSONTEST_ASSERT(flat.isObject());
  JSONTEST_ASSERT_EQUAL(1u, flat.size());
  JSONTEST_ASSERT_EQUAL(42, flat[""].asInt());
}

JSONTEST_FIXTURE_LOCAL(FlattenTest, arrayRootAndNestedArrays) {
  Json::Value flat = parse(R"([[true],{"k":"v"}])").flatten();
  JSONTEST_ASSERT_EQUAL(2u, flat.size());
  JSONTEST_ASSERT(flat["0.0"].asBool());
  JSONTEST_ASSERT_STRING_EQUAL("v", flat["1.k"].asString());
}

JSONTEST_FIXTURE_LOCAL(FlattenTest, originalIsUnchanged) {
  Json::Value doc = parse(R"({"a":{"b":1}})");
  Json::Value before = doc;
  doc.flatten();
  JSONTEST_ASSERT(doc == before);
}

int main(int argc, const char* argv[]) {
  JsonTest::Runner runner;
  for (auto& local : local_)
    runner.add(local);
  return runner.runCommandLine(argc, argv);
}
